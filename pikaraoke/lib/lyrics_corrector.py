"""Online lyrics correction for Whisper transcription output.

Fetches synced lyrics (LRC) via syncedlyrics and uses them to fix
Whisper homophone errors at the character level, preserving Whisper's
word-level timing for karaoke animation.
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

# Minimum fraction of online lyric lines that must text-match SOME Whisper line for the online
# LRC to be trusted. Below this the title search almost certainly returned a different song.
_MIN_LYRICS_MATCH_FRACTION = 0.30


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


def _interpolate_into(
    result: list[dict], chars: list[str], span_start: float, span_end: float
) -> None:
    """Append ``chars`` spread evenly across [span_start, span_end] onto ``result``.

    Used for online chars with no matching Whisper char (insertions / unequal replacements):
    they fill the time span between their anchored neighbours.
    """
    if not chars:
        return
    if span_end <= span_start:
        # No real gap (e.g. trailing excess chars): continue at the previous tempo.
        last_end = result[-1]["end"] if result else span_start
        avg = sum(r["end"] - r["start"] for r in result) / len(result) if result else 0.3
        for ch in chars:
            result.append({"word": ch, "start": last_end, "end": last_end + avg})
            last_end += avg
        return
    dur = (span_end - span_start) / len(chars)
    for k, ch in enumerate(chars):
        result.append(
            {"word": ch, "start": span_start + k * dur, "end": span_start + (k + 1) * dur}
        )


def _align_chars_by_opcodes(
    whisper_chars: list[dict], online_chars: list[str]
) -> list[dict]:
    """Align online display chars to Whisper char timings via edit-distance opcodes.

    Anchors matched (or equal-length homophone) chars to their true Whisper timing and only
    interpolates online chars across unmatched runs. A single Whisper insertion/deletion no
    longer shifts the whole remainder of the line (the positional-zip drift bug).
    """
    whisper_norm = [_normalize_for_comparison(wc["word"]) for wc in whisper_chars]
    online_norm = [_normalize_for_comparison(ch) for ch in online_chars]

    result: list[dict] = []
    matcher = SequenceMatcher(None, whisper_norm, online_norm, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "delete":
            # Whisper-only chars (interjections / hallucinations): no online char to emit.
            continue
        if (i2 - i1) == (j2 - j1):
            # 1:1 correspondence (exact match or equal-length homophone swap): each online
            # char inherits its true Whisper char timing.
            for k in range(j2 - j1):
                wc = whisper_chars[i1 + k]
                result.append(
                    {"word": online_chars[j1 + k], "start": wc["start"], "end": wc["end"]}
                )
            continue
        # Unequal replace / pure insert: interpolate online chars across the matched span.
        if i2 > i1:
            span_start = whisper_chars[i1]["start"]
            span_end = whisper_chars[i2 - 1]["end"]
        else:
            span_start = whisper_chars[i1 - 1]["end"] if i1 > 0 else whisper_chars[0]["start"]
            span_end = (
                whisper_chars[i1]["start"]
                if i1 < len(whisper_chars)
                else whisper_chars[-1]["end"]
            )
        _interpolate_into(result, online_chars[j1:j2], span_start, span_end)
    return result


def _map_chars_to_whisper_words(
    online_text: str,
    whisper_words: list[dict],
    is_cjk: bool = False,
    line_end: float | None = None,
) -> list[dict]:
    """Map online text characters to Whisper word timestamps.

    Uses Whisper words as timing source, online text as display. Each Whisper word's duration
    is subdivided across its characters, then online chars are aligned to those per-char
    timings by edit distance (_align_chars_by_opcodes) so insertions/deletions don't drift.
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

    return _align_chars_by_opcodes(whisper_chars, online_chars)


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


def _lyrics_text_match_fraction(
    online_segments: list[dict], whisper_segments: list[dict]
) -> float:
    """Fraction of online lines with a strong (>0.6) text match to some Whisper line.

    A low fraction means the online LRC is almost certainly a DIFFERENT song (cover / live /
    wrong title match) and should be rejected rather than shown as confidently-wrong subtitles.
    """
    whisper_norm = [
        n for w in whisper_segments if (n := _normalize_for_comparison(w.get("text", "")))
    ]
    if not whisper_norm:
        return 0.0
    matched = 0
    considered = 0
    for oseg in online_segments:
        o_text = _normalize_for_comparison(oseg.get("text", ""))
        if not o_text:
            continue
        considered += 1
        best = max(
            (SequenceMatcher(None, o_text, w).ratio() for w in whisper_norm), default=0.0
        )
        if best > 0.6:
            matched += 1
    return matched / considered if considered else 0.0


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

    # Reject a wrong-song LRC: if almost no online line text-matches the Whisper transcript the
    # title search returned a different song, and showing it would be confidently-wrong text.
    if _lyrics_text_match_fraction(online_segments, whisper_segments) < _MIN_LYRICS_MATCH_FRACTION:
        logging.info("Online lyrics text match too low, rejecting as likely wrong song")
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

        # Align whisper chars to online chars by edit distance; only EQUAL-LENGTH replace runs
        # are safe homophone swaps. Insert/delete runs would cascade under a positional walk
        # (corrupting an otherwise-correct line), so keep Whisper's char there.
        w_flat = [ch for w in words for ch in w.get("word", "").strip()]
        corrected_chars = list(w_flat)
        sm = SequenceMatcher(None, w_flat, list(o_chars), autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "replace" and (i2 - i1) == (j2 - j1):
                for k in range(i2 - i1):
                    if corrected_chars[i1 + k] != o_chars[j1 + k]:
                        corrected_chars[i1 + k] = o_chars[j1 + k]
                        corrected_count += 1

        # Redistribute corrected chars back into words, preserving per-word timing.
        new_words = []
        p = 0
        for w in words:
            word_text = w.get("word", "").strip()
            if not word_text:
                new_words.append(w)
                continue
            corrected_word = "".join(corrected_chars[p : p + len(word_text)])
            p += len(word_text)
            new_words.append({"word": corrected_word, "start": w["start"], "end": w["end"]})

        sep = "" if _has_cjk(w_text) else " "
        corrected_text = sep.join(
            nw["word"].strip() for nw in new_words if nw["word"].strip()
        )
        result.append(
            {
                "start": wseg["start"],
                "end": wseg["end"],
                "text": corrected_text,
                "words": new_words,
            }
        )

    if corrected_count > 0:
        logging.info("Corrected %d characters with online lyrics", corrected_count)
    return result
