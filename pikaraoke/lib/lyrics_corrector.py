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

    Uses online text (accurate, human-written) combined with Whisper's
    word-level timing. Falls back to even interpolation when no matching
    Whisper segment is found for a given online line.

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

    aligned = []
    matched_count = 0
    used_whisper_ids: set[int] = set()  # Track used Whisper segments by id

    for oseg in online_segments:
        o_text = oseg.get("text", "").strip()
        o_start = oseg.get("start", 0.0)
        o_end = oseg.get("end", o_start + 5.0)
        if not o_text:
            continue

        # Find best matching Whisper segment (not already used)
        best_wseg = None
        best_score = 0.0
        for wseg in whisper_segments:
            if id(wseg) in used_whisper_ids:
                continue
            w_start = wseg.get("start", 0.0)
            time_dist = abs(o_start - w_start)
            if time_dist > 5.0:
                continue
            w_text = wseg.get("text", "").strip()
            w_chars = _normalize_for_comparison(w_text)
            o_chars = _normalize_for_comparison(o_text)
            if not w_chars or not o_chars:
                continue
            ratio = SequenceMatcher(None, w_chars, o_chars).ratio()
            score = ratio * (1 - time_dist / 10.0)
            if score > best_score and ratio > 0.4:
                best_score = score
                best_wseg = wseg

        is_cjk = _has_cjk(o_text)

        if best_wseg and best_wseg.get("words"):
            used_whisper_ids.add(id(best_wseg))
            whisper_words = best_wseg["words"]
            w_start = whisper_words[0].get("start", o_start)
            w_end = whisper_words[-1].get("end", o_end)

            if is_cjk:
                words = _interpolate_word_timing(o_text, w_start, w_end, is_cjk=True)
            else:
                online_words = o_text.split()
                if len(online_words) == len(whisper_words):
                    words = [
                        {"word": ow, "start": ww["start"], "end": ww["end"]}
                        for ow, ww in zip(online_words, whisper_words)
                    ]
                else:
                    words = _interpolate_word_timing(o_text, w_start, w_end, is_cjk=False)

            matched_count += 1
        else:
            # No Whisper match — use LRC timestamps (still accurate for line timing)
            words = _interpolate_word_timing(o_text, o_start, o_end, is_cjk=is_cjk)

        aligned.append({
            "start": words[0]["start"] if words else o_start,
            "end": words[-1]["end"] if words else o_end,
            "text": o_text,
            "words": words,
        })

    # Quality gate: if less than 20% of online lines matched Whisper, alignment
    # is unreliable (probably wrong song version). Return None to trigger fallback.
    # Threshold is low because partial alignment (online text + interpolated timing)
    # is still better than Whisper-only text with errors.
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
