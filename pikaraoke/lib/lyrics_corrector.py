"""Online lyrics correction for Whisper transcription output.

Fetches synced lyrics (LRC) via syncedlyrics and uses them to fix
Whisper homophone errors at the character level, preserving Whisper's
word-level timing for karaoke animation.
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher


def _parse_lrc_line(line: str) -> tuple[float, str] | None:
    """Parse an LRC timestamp line like '[01:23.45]lyrics text'."""
    m = re.match(r"\[(\d+):(\d+)\.(\d+)\](.*)", line.strip())
    if not m:
        return None
    minutes, seconds, centis, text = m.groups()
    timestamp = int(minutes) * 60 + int(seconds) + int(centis) / 100
    return timestamp, text.strip()


def _clean_search_title(title: str) -> str:
    """Clean YouTube video title to extract artist + song name for lyrics search."""
    # Remove YouTube ID suffix (---xxxxx)
    title = re.sub(r"---[\w-]{11}(\.\w+)?$", "", title)
    # Remove file extension
    title = re.sub(r"\.\w{3,4}$", "", title)
    # Remove common noise words
    noise = [
        r"\(?official\s*(music\s*)?video\)?",
        r"\(?official\s*MV\)?",
        r"\(?MV\)?",
        r"\(?HQ\)?",
        r"官方版",
        r"官方MV",
        r"完整版",
        r"lyrics?\s*video",
        r"with\s*lyrics",
        r"full\s*version",
        r"\(?HD\)?",
        r"\(?4K\)?",
        r"\(?1080p\)?",
    ]
    for pat in noise:
        title = re.sub(pat, "", title, flags=re.IGNORECASE)
    # Remove brackets with content like <...> [...] (...)
    title = re.sub(r"[〈〉【】\[\]]", " ", title)
    # Clean up whitespace
    title = re.sub(r"\s+", " ", title).strip()
    # Remove trailing punctuation
    title = title.rstrip(" -_")
    return title


def _is_credit_line(text: str) -> bool:
    """Check if a lyrics line is actually a credit/metadata line."""
    from pikaraoke.lib.karaoke_subtitle import _HALLUCINATION_KEYWORDS

    text_lower = text.lower().strip()
    return any(kw in text_lower for kw in _HALLUCINATION_KEYWORDS)


def _search_online_lyrics(title: str) -> list[dict] | None:
    """Search for synced lyrics (LRC) online. Returns parsed segments or None."""
    try:
        import syncedlyrics

        clean_title = _clean_search_title(title)
        logging.info("Searching online lyrics for: '%s'", clean_title)
        lrc = syncedlyrics.search(clean_title, synced_only=True)
        if not lrc:
            return None

        segments = []
        lines = [_parse_lrc_line(ln) for ln in lrc.splitlines() if ln.strip()]
        parsed = [p for p in lines if p and p[1]]

        # Filter out credit/metadata lines (作詞, 作曲, etc.)
        parsed = [(t, txt) for t, txt in parsed if not _is_credit_line(txt)]

        # Validation: reject if too few lines (likely wrong match)
        if len(parsed) < 5:
            logging.warning("Online lyrics too short (%d lines), skipping", len(parsed))
            return None

        for i, (start, text) in enumerate(parsed):
            end = parsed[i + 1][0] if i + 1 < len(parsed) else start + 5.0
            segments.append({"start": start, "end": end, "text": text, "words": []})

        logging.info("Found online synced lyrics: %d lines for '%s'", len(segments), clean_title)
        return segments if segments else None
    except Exception as e:  # broad catch: third-party syncedlyrics can raise arbitrary exceptions
        logging.warning("Online lyrics search failed: %s", e)
        return None


def _map_chars_to_whisper_words(
    online_text: str,
    whisper_words: list[dict],
    is_cjk: bool = False,
    line_end: float | None = None,
) -> list[dict]:
    """Map online text characters to Whisper word timestamps.

    Uses Whisper words as timing source, online text as display.
    Each Whisper word's duration is subdivided across its characters,
    then online characters inherit these per-character timings.
    Excess characters use line_end for even distribution (not 0.1s).
    """
    # Build per-character timing from Whisper words
    whisper_chars: list[dict] = []
    for ww in whisper_words:
        w_text = ww.get("word", "").strip()
        w_start = ww.get("start", 0.0)
        w_end = ww.get("end", w_start + 0.1)
        if not w_text:
            continue
        chars = [c for c in w_text if not c.isspace()] if is_cjk else [w_text]
        n = len(chars)
        dur = (w_end - w_start) / max(n, 1)
        for j in range(n):
            whisper_chars.append({
                "word": chars[j],
                "start": w_start + j * dur,
                "end": w_start + (j + 1) * dur,
            })

    # Map online characters to Whisper character timings
    online_chars = [c for c in online_text if not c.isspace()] if is_cjk else online_text.split()
    if not online_chars or not whisper_chars:
        start = whisper_words[0]["start"] if whisper_words else 0
        end = line_end or (whisper_words[-1]["end"] if whisper_words else 1)
        return _interpolate_word_timing(online_text, start, end, is_cjk)

    result = []
    for i, ch in enumerate(online_chars):
        if i < len(whisper_chars):
            result.append({"word": ch, "start": whisper_chars[i]["start"], "end": whisper_chars[i]["end"]})
        else:
            # Excess chars: use average duration of already-mapped chars
            # (maintains same singing tempo as the first part of the line)
            if result:
                avg_dur = sum(r["end"] - r["start"] for r in result) / len(result)
            else:
                avg_dur = 0.3
            last_end = result[-1]["end"] if result else whisper_chars[-1]["end"]
            result.append({"word": ch, "start": last_end, "end": last_end + avg_dur})

    return result


def _interpolate_word_timing(
    text: str, start: float, end: float, is_cjk: bool = False
) -> list[dict]:
    """Create word-level timing by evenly distributing duration.

    For CJK text, each character gets equal time (1 char ~ 1 syllable).
    For non-CJK, split by spaces and distribute.
    """
    if is_cjk:
        chars = [ch for ch in text if not ch.isspace()]
    else:
        chars = text.split()
    if not chars:
        return [{"word": text, "start": start, "end": end}]
    dur = (end - start) / len(chars)
    return [
        {"word": ch, "start": start + i * dur, "end": start + (i + 1) * dur}
        for i, ch in enumerate(chars)
    ]


def _has_cjk(text: str) -> bool:
    """Check if text contains CJK characters."""
    return any(
        0x4E00 <= ord(c) <= 0x9FFF
        or 0x3040 <= ord(c) <= 0x30FF
        or 0xAC00 <= ord(c) <= 0xD7AF
        for c in text
    )


def _normalize_for_comparison(text: str) -> str:
    """Normalize text for comparison by converting to simplified Chinese.

    Online LRC may be traditional, Whisper may be simplified (or vice versa).
    Converting both to simplified ensures consistent comparison.
    """
    text = re.sub(r"\s+", "", text)
    try:
        from opencc import OpenCC

        cc = OpenCC("t2s")
        return cc.convert(text)
    except ImportError:
        return text


def _estimate_global_offset(
    online_segments: list[dict], whisper_segments: list[dict]
) -> float:
    """Estimate global time offset between online LRC and Whisper timestamps.

    Online LRC may be from album version while Whisper runs on the MV,
    which often has a different intro length. This calculates the median
    offset by matching lines purely on text similarity (ignoring time).
    """
    offsets = []
    for oseg in online_segments:
        o_text = _normalize_for_comparison(oseg.get("text", ""))
        if not o_text:
            continue
        best_ratio = 0.0
        best_offset = 0.0
        for wseg in whisper_segments:
            w_text = _normalize_for_comparison(wseg.get("text", ""))
            if not w_text:
                continue
            ratio = SequenceMatcher(None, o_text, w_text).ratio()
            if ratio > best_ratio and ratio > 0.6:
                best_ratio = ratio
                best_offset = oseg["start"] - wseg["start"]
        if best_ratio > 0.6:
            offsets.append(best_offset)
    if not offsets:
        return 0.0
    offsets.sort()
    return offsets[len(offsets) // 2]


def align_online_with_whisper_timing(
    online_segments: list[dict],
    whisper_segments: list[dict],
    language: str = "",
) -> list[dict] | None:
    """Align online lyrics text with Whisper word-level timestamps.

    Uses a flat Whisper word timeline (not segment matching) to ensure
    every character gets real timing. Online text provides the display,
    Whisper words provide the timing.

    Returns aligned segments, or None if alignment quality is too low.
    """
    if not online_segments or not whisper_segments:
        return None

    # Estimate and apply global time offset (album vs MV timing)
    offset = _estimate_global_offset(online_segments, whisper_segments)
    if abs(offset) > 1.0:
        logging.info("Global LRC-Whisper offset: %.1fs, applying correction", offset)
        online_segments = [
            {**seg, "start": seg["start"] - offset, "end": seg["end"] - offset}
            for seg in online_segments
        ]

    # Flatten ALL Whisper words into a single sorted timeline
    all_words: list[dict] = []
    for wseg in whisper_segments:
        for w in wseg.get("words", []):
            if w.get("word", "").strip():
                all_words.append(w)
    all_words.sort(key=lambda w: w.get("start", 0))

    if not all_words:
        return None

    # Walk through online lines and word timeline in parallel
    aligned = []
    matched_count = 0
    word_cursor = 0

    for oseg in online_segments:
        o_text = oseg.get("text", "").strip()
        o_start = oseg.get("start", 0.0)
        o_end = oseg.get("end", o_start + 5.0)
        if not o_text:
            continue

        is_cjk = _has_cjk(o_text)

        # Skip words before this line's range
        while word_cursor < len(all_words) and all_words[word_cursor]["start"] < o_start - 1.0:
            word_cursor += 1

        # Collect words within this line's time range
        # Cap at 10s to prevent long gaps (interludes) from consuming next line's words
        collect_end = min(o_end + 1.0, o_start + 10.0)
        line_words: list[dict] = []
        scan = word_cursor
        while scan < len(all_words) and all_words[scan]["start"] <= collect_end:
            line_words.append(all_words[scan])
            scan += 1

        if line_words:
            # Advance cursor past used words
            word_cursor = scan
            words = _map_chars_to_whisper_words(
                o_text, line_words, is_cjk=is_cjk, line_end=o_end
            )
            matched_count += 1
        else:
            # No Whisper words in range — use LRC timestamps
            words = _interpolate_word_timing(o_text, o_start, o_end, is_cjk=is_cjk)

        aligned.append({
            "start": words[0]["start"] if words else o_start,
            "end": words[-1]["end"] if words else o_end,
            "text": o_text,
            "words": words,
        })

    # Quality gate: reject if too few online lines got Whisper timing
    if len(online_segments) > 0 and matched_count / len(online_segments) < 0.2:
        logging.info(
            "Online-Whisper alignment too low (%d/%d matched), falling back",
            matched_count,
            len(online_segments),
        )
        return None

    logging.info(
        "Aligned %d online lines (%d with Whisper timing)",
        len(aligned),
        matched_count,
    )
    return aligned if aligned else None


def _correct_typos_with_online_lyrics(
    whisper_segments: list[dict], online_segments: list[dict]
) -> list[dict]:
    """Correct Whisper homophone errors using online lyrics as reference.

    Only replaces individual characters when the overall line similarity
    is high (>60%), keeping Whisper's text structure and word timing intact.
    Does NOT replace entire lines -- only fixes likely typos.
    """
    online_lines = [(seg["start"], seg["text"]) for seg in online_segments if seg["text"]]
    if not online_lines:
        return whisper_segments

    corrected_count = 0
    result = []
    for wseg in whisper_segments:
        w_text = wseg.get("text", "").strip()
        w_start = wseg.get("start", 0)
        words = wseg.get("words", [])

        # Find closest online line by timestamp (within 3 second window)
        best_match = None
        best_dist = 3.0
        for o_start, o_text in online_lines:
            dist = abs(w_start - o_start)
            if dist < best_dist:
                best_dist = dist
                best_match = o_text

        if not best_match or not words:
            result.append(wseg)
            continue

        # Check similarity -- only correct if >60% similar (same line, minor typos)
        w_chars = w_text.replace(" ", "")
        o_chars = best_match.replace(" ", "")
        ratio = SequenceMatcher(None, w_chars, o_chars).ratio()

        if ratio < 0.6:
            # Too different -- probably wrong match, keep Whisper as-is
            result.append(wseg)
            continue

        if ratio > 0.99:
            # Already identical, no correction needed
            result.append(wseg)
            continue

        # Character-level correction: replace individual wrong chars in each word
        o_idx = 0
        new_words = []
        for w in words:
            word_text = w.get("word", "").strip()
            if not word_text:
                new_words.append(w)
                continue

            corrected_word = ""
            for ch in word_text:
                if o_idx < len(o_chars) and ch != o_chars[o_idx]:
                    # Replace with online character (likely correct)
                    corrected_word += o_chars[o_idx]
                    corrected_count += 1
                elif o_idx < len(o_chars):
                    corrected_word += ch
                else:
                    corrected_word += ch
                o_idx += 1

            new_words.append(
                {
                    "word": corrected_word,
                    "start": w["start"],
                    "end": w["end"],
                }
            )

        result.append(
            {
                "start": wseg["start"],
                "end": wseg["end"],
                "text": best_match,
                "words": new_words,
            }
        )

    if corrected_count > 0:
        logging.info("Corrected %d characters with online lyrics", corrected_count)
    return result
