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
