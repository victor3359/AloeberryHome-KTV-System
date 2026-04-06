"""ASS subtitle generation for karaoke lyrics.

Generates ASS subtitle files with karaoke timing tags (kf) from Whisper
transcription segments. SubtitlesOctopus/libass renders these as
left-to-right color-changing lyrics during playback.
"""

from __future__ import annotations

import re

_HALLUCINATION_KEYWORDS = [
    # Chinese credits
    "詞曲",
    "词曲",
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

        cc = OpenCC("s2twp")
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


def _build_kf_text(
    words: list[dict], timing_offset: float
) -> tuple[str, float, float]:
    """Build karaoke fill text from word-level timestamps.

    Returns (kf_tagged_text, seg_start, seg_end). No pre-display pad —
    Preview lines handle the advance display role.
    Caps outlier durations that result from Whisper segment boundary inflation.
    """
    seg_start = words[0]["start"] + timing_offset
    seg_end = words[-1]["end"] + timing_offset

    # First pass: collect (char_text, dur_cs) pairs
    char_data: list[tuple[str, int]] = []
    for word_info in words:
        word = word_info.get("word", "").strip()
        if not word:
            continue
        w_start = word_info.get("start", 0.0) + timing_offset
        w_end = word_info.get("end", w_start + 0.1) + timing_offset

        char_parts = _split_cjk_word(word, w_start, w_end)
        for char_text, c_start, c_end in char_parts:
            dur_cs = max(int((c_end - c_start) * 100), 5)
            char_text = _to_traditional_chinese(char_text)
            char_data.append((char_text, dur_cs))

    # Cap outlier durations: Whisper inflates last words at segment boundaries
    if len(char_data) > 2:
        durations = sorted(d for _, d in char_data)
        median = durations[len(durations) // 2]
        cap = max(int(median * 2.5), 80)  # At least 0.8s, cap at 2.5x median
        char_data = [(ch, min(d, cap)) for ch, d in char_data]

    # Recalculate seg_end from actual kf durations (not Whisper's inflated end time)
    total_cs = sum(d for _, d in char_data)
    seg_end = seg_start + total_cs / 100.0

    # Build kf tagged text
    parts: list[str] = []
    for i, (char_text, dur_cs) in enumerate(char_data):
        prefix = " " if i > 0 and not _is_cjk_char(char_text[0]) else ""
        parts.append(f"{{\\kf{dur_cs}}}{prefix}{char_text}")

    return "".join(parts), seg_start, seg_end


def generate_karaoke_ass(segments: list[dict], title: str = "", timing_offset: float = -0.7) -> str:
    """Generate ASS subtitle with two-line KTV layout.

    Active line: cream white text fills to warm amber word by word.
    Preview line: soft gray text showing the next line.

    Args:
        segments: List of segments with 'words' and/or 'text'.
        title: Song title for script info.
        timing_offset: Seconds to shift fill animation timing.

    Returns:
        Complete ASS file content as a string.
    """
    # Positions for 3840x2160 PlayRes
    active_y = 1960
    preview_y = 1760

    header = f"""[Script Info]
Title: {title}
ScriptType: v4.00+
PlayResX: 3840
PlayResY: 2160
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Active,DroidSansFallback,168,&H00E0F3FA,&H007CA8E8,&H00000000,&H80000000,1,0,0,0,100,100,2,0,1,6,3,2,80,80,120,1
Style: Preview,DroidSansFallback,148,&H508B8B8B,&H508B8B8B,&H00000000,&H80000000,0,0,0,0,100,100,2,0,1,4,2,2,80,80,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header.strip()]
    pre_display = 1.5

    # First pass: build line data (kf_text, plain_text, start, end)
    line_data: list[tuple[str, str, float, float]] = []
    for segment in segments:
        words = segment.get("words", [])
        if not words:
            text = _to_traditional_chinese(segment.get("text", "").strip())
            if not text:
                continue
            start = segment.get("start", 0.0) + timing_offset
            end = segment.get("end", start + 1.0) + timing_offset
            dur_cs = max(int((end - start) * 100), 10)
            kf = f"{{\\kf{dur_cs}}}{text}"
            line_data.append((kf, text, start, end))
            continue

        kf_text, seg_start, seg_end = _build_kf_text(words, timing_offset)
        if kf_text:
            plain = _to_traditional_chinese(segment.get("text", "").strip())
            line_data.append((kf_text, plain, seg_start, seg_end))

    # Second pass: seamless two-line KTV alternating layout
    # Odd lines (0,2,4..) at bottom (active_y), even lines (1,3,5..) at top (preview_y)
    # Preview appears at same position as its future Active, so transition is in-place.
    #
    # Timeline:
    #   ----A singing----  ----B singing----  ----C singing----
    #   bottom: [A active]  [C preview gray]  [C active]
    #   top:    [B preview]  [B active]       [D preview gray]
    pos_list = [active_y, preview_y]
    # Track when each position becomes free (prevent overlap)
    pos_free_at = {active_y: 0.0, preview_y: 0.0}

    for i, (kf_text, plain_text, start, end) in enumerate(line_data):
        my_y = pos_list[i % 2]

        # Active: starts when position is free, ends at singing end
        actual_start = max(start, pos_free_at[my_y])
        pos_free_at[my_y] = end
        lines.append(
            f"Dialogue: 1,{_format_ass_time(actual_start)},{_format_ass_time(end)},Active,,0,0,0,,"
            f"{{\\an2\\pos(1920,{my_y})}}{kf_text}"
        )

        # Preview for NEXT line at the OTHER position
        if i + 1 < len(line_data):
            _, next_plain, next_start, _ = line_data[i + 1]
            next_y = pos_list[(i + 1) % 2]
            if next_plain:
                preview_begin = max(actual_start, pos_free_at[next_y])
                preview_finish = next_start
                if preview_finish > preview_begin + 0.3:
                    pos_free_at[next_y] = preview_finish
                    lines.append(
                        f"Dialogue: 0,{_format_ass_time(preview_begin)},{_format_ass_time(preview_finish)},Preview,,0,0,0,,"
                        f"{{\\an2\\pos(1920,{next_y})}}{next_plain}"
                    )

    return "\n".join(lines) + "\n"
