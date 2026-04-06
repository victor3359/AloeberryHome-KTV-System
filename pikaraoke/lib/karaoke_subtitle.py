"""ASS subtitle generation for karaoke lyrics.

Generates ASS subtitle files with karaoke timing tags (kf) from Whisper
transcription segments. SubtitlesOctopus/libass renders these as
left-to-right color-changing lyrics during playback.
"""

from __future__ import annotations

import re

_HALLUCINATION_KEYWORDS = [
    # Chinese credits
    "作詞",
    "作曲",
    "編曲",
    "填詞",
    "監製",
    "製作人",
    "主唱",
    "演唱",
    "原唱",
    "翻唱",
    "混音",
    "錄音",
    "母帶",
    "出品",
    # English credits
    "lyrics by",
    "composed by",
    "music by",
    "arranged by",
    "written by",
    "produced by",
    "directed by",
    "mixed by",
    "mastered by",
    "performed by",
    # Subtitles / metadata
    "字幕",
    "歌詞提供",
    "字幕提供",
    "music video",
    "official mv",
    "copyright",
    "版權",
    "all rights reserved",
    # Social media / ads
    "subscribe",
    "訂閱",
    "點讚",
    "like and subscribe",
    "please subscribe",
    "like comment",
    "subtitles",
    "captions",
    # Closing markers
    "感謝觀看",
    "感谢观看",
    "謝謝收看",
]

_HALLUCINATION_PATTERNS = [
    re.compile(r"^[\s.。，,、…♪♫🎵🎶─\-~]+$"),  # Only punctuation / music symbols
    re.compile(r"(.{1,4})\1{3,}"),  # Short phrase repeated 4+ times
    re.compile(r"^(the )?(end|fin|終|完)\.?$", re.IGNORECASE),  # End markers
    re.compile(r"^\d+$"),  # Pure numbers
]


def _is_cjk_char(ch: str) -> bool:
    """Check if a character is CJK (Chinese, Japanese kana, Korean hangul)."""
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF  # CJK Unified Ideographs
        or 0x3400 <= cp <= 0x4DBF  # CJK Extension A
        or 0x3040 <= cp <= 0x30FF  # Hiragana + Katakana
        or 0xAC00 <= cp <= 0xD7AF  # Korean Hangul syllables
    )


def _split_cjk_word(
    word: str, start: float, end: float
) -> list[tuple[str, float, float]]:
    """Split a CJK word into per-character timing.

    Each CJK character is roughly one syllable, so evenly distributing
    the word duration gives smooth per-character fill animation.
    Non-CJK words are returned as-is.
    """
    chars = list(word.strip())
    if len(chars) <= 1:
        return [(word, start, end)]

    cjk_count = sum(1 for c in chars if _is_cjk_char(c))
    if cjk_count < len(chars) * 0.5:
        return [(word, start, end)]

    duration = end - start
    char_dur = duration / len(chars)
    return [
        (ch, start + i * char_dur, start + (i + 1) * char_dur)
        for i, ch in enumerate(chars)
    ]


def _format_ass_time(seconds: float) -> str:
    """Format seconds as ASS timestamp H:MM:SS.cc."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _to_traditional_chinese(text: str) -> str:
    """Convert simplified Chinese to traditional Chinese."""
    try:
        from opencc import OpenCC

        cc = OpenCC("s2t")
        return cc.convert(text)
    except ImportError:
        return text


def _filter_whisper_hallucinations(segments: list[dict]) -> list[dict]:
    """Filter out Whisper hallucinated segments (fake text during silence).

    Common hallucinations: repeated text, composer/lyricist credits,
    nonsensical repetitions during instrumental intros/outros.
    """
    filtered = []
    seen_texts: dict[str, int] = {}
    prev_normalized = ""

    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue

        # Skip very short segments (likely noise)
        duration = seg.get("end", 0) - seg.get("start", 0)
        if duration < 0.1:
            continue

        # Skip segments with high no_speech_prob (silence detected)
        if seg.get("no_speech_prob", 0) > 0.4:
            continue

        # Skip suspiciously long segments (normal lyric line is 2-10s)
        if duration > 20:
            continue

        # Skip single-character noise fragments
        text_chars = re.sub(r"\s+", "", text)
        if len(text_chars) <= 1 and duration < 1.0:
            continue

        # Keyword-based hallucination detection (case-insensitive substring match)
        text_lower = text.lower()
        if any(kw in text_lower for kw in _HALLUCINATION_KEYWORDS):
            continue

        # Regex pattern-based hallucination detection
        if any(pat.search(text) for pat in _HALLUCINATION_PATTERNS):
            continue

        # Track repeated text -- hallucination repeats same phrase
        normalized = re.sub(r"\s+", "", text)
        seen_texts[normalized] = seen_texts.get(normalized, 0) + 1
        if seen_texts[normalized] > 3:
            continue

        # Skip consecutive identical lines (adjacent duplicates)
        if normalized == prev_normalized:
            continue
        prev_normalized = normalized

        filtered.append(seg)

    return filtered


def generate_karaoke_ass(segments: list[dict], title: str = "", timing_offset: float = -0.3) -> str:
    """Generate ASS subtitle content with karaoke timing tags.

    Args:
        segments: List of Whisper segments, each with 'words' containing
                  {'word': str, 'start': float, 'end': float}.
        title: Song title for the script info.
        timing_offset: Seconds to delay subtitle fill animation (positive = later).
                       Compensates for Whisper detecting word onsets slightly early.

    Returns:
        Complete ASS file content as a string.
    """
    header = f"""[Script Info]
Title: {title}
ScriptType: v4.00+
PlayResX: 3840
PlayResY: 2160
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,Arial,168,&H0000D7FF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,2,0,1,8,5,2,80,80,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header.strip()]

    # Pre-display: show lyrics 1.5s before singing starts
    # Timing offset: delay fill animation to match actual vocal onset
    pre_display = 1.5

    for segment in segments:
        words = segment.get("words", [])
        if not words:
            text = _to_traditional_chinese(segment.get("text", "").strip())
            if not text:
                continue
            start = segment.get("start", 0.0) + timing_offset
            end = segment.get("end", start + 1.0) + timing_offset
            duration_cs = max(int((end - start) * 100), 10)
            early_start = max(0, start - pre_display)
            pad_cs = int((start - early_start) * 100)
            ass_start = _format_ass_time(early_start)
            ass_end = _format_ass_time(end + 0.5)
            if pad_cs > 0:
                lines.append(
                    f"Dialogue: 0,{ass_start},{ass_end},Karaoke,,0,0,0,,"
                    f"{{\\kf{pad_cs}}}{{\\kf{duration_cs}}}{text}"
                )
            else:
                lines.append(
                    f"Dialogue: 0,{ass_start},{ass_end},Karaoke,,0,0,0,,{{\\kf{duration_cs}}}{text}"
                )
            continue

        # Build karaoke line from word-level timestamps (with offset)
        seg_start = words[0]["start"] + timing_offset
        seg_end = words[-1]["end"] + timing_offset
        early_start = max(0, seg_start - pre_display)
        pad_cs = int((seg_start - early_start) * 100)
        ass_start = _format_ass_time(early_start)
        ass_end = _format_ass_time(seg_end + 0.5)

        karaoke_parts = []
        if pad_cs > 0:
            karaoke_parts.append(f"{{\\kf{pad_cs}}}")
        for word_info in words:
            word = word_info.get("word", "").strip()
            if not word:
                continue
            w_start = word_info.get("start", 0.0) + timing_offset
            w_end = word_info.get("end", w_start + 0.1) + timing_offset

            # Split CJK words into per-character timing for smooth fill
            char_parts = _split_cjk_word(word, w_start, w_end)
            for char_text, c_start, c_end in char_parts:
                dur_cs = max(int((c_end - c_start) * 100), 5)
                has_prev = len(karaoke_parts) > (1 if pad_cs > 0 else 0)
                prefix = " " if has_prev and not _is_cjk_char(char_text[0]) else ""
                char_text = _to_traditional_chinese(char_text)
                karaoke_parts.append(f"{{\\kf{dur_cs}}}{prefix}{char_text}")

        if karaoke_parts:
            text = "".join(karaoke_parts)
            lines.append(f"Dialogue: 0,{ass_start},{ass_end},Karaoke,,0,0,0,,{text}")

    return "\n".join(lines) + "\n"
