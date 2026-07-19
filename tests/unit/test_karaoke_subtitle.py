"""Unit tests for karaoke_subtitle module."""

from __future__ import annotations

import os
import re

from pikaraoke.lib.karaoke_subtitle import (
    _build_kf_text,
    _filter_whisper_hallucinations,
    _is_cjk_char,
    _split_cjk_word,
    generate_karaoke_ass,
)


class TestKfTextTraditionalConversion:
    def test_converts_whole_word_not_per_char(self, monkeypatch):
        """P1-5: OpenCC s2twp needs phrase context — 干杯 -> 乾杯 (correct) but per-char
        干 -> 幹 (wrong, vulgar reading). Convert the whole word before splitting it into
        karaoke chars, never each split CJK char in isolation."""
        seen = []
        monkeypatch.setattr(
            "pikaraoke.lib.karaoke_subtitle._to_traditional_chinese",
            lambda t: (seen.append(t), t)[1],
        )
        _build_kf_text([{"word": "干杯", "start": 0.0, "end": 1.0}], timing_offset=0.0)
        assert "干杯" in seen, "the whole word must be converted with phrase context"
        assert "干" not in seen and "杯" not in seen, "must not convert per split char"


class TestIsCjkChar:
    def test_chinese(self):
        assert _is_cjk_char("紅")
        assert _is_cjk_char("愛")

    def test_japanese_hiragana(self):
        assert _is_cjk_char("あ")

    def test_japanese_katakana(self):
        assert _is_cjk_char("ア")

    def test_korean_hangul(self):
        assert _is_cjk_char("가")

    def test_latin_not_cjk(self):
        assert not _is_cjk_char("A")
        assert not _is_cjk_char("z")

    def test_digit_not_cjk(self):
        assert not _is_cjk_char("1")

    def test_punctuation_not_cjk(self):
        assert not _is_cjk_char(",")


class TestSplitCjkWord:
    def test_chinese_word_splits_evenly(self):
        result = _split_cjk_word("紅塵作伴", 1.0, 2.2)
        assert len(result) == 4
        assert result[0][0] == "紅"
        assert result[3][0] == "伴"
        # Each char gets 0.3s (1.2s / 4)
        assert abs(result[0][2] - result[0][1] - 0.3) < 0.01

    def test_single_char_no_split(self):
        result = _split_cjk_word("愛", 1.0, 1.5)
        assert len(result) == 1
        assert result[0] == ("愛", 1.0, 1.5)

    def test_english_word_no_split(self):
        result = _split_cjk_word("love", 1.0, 2.0)
        assert len(result) == 1
        assert result[0] == ("love", 1.0, 2.0)

    def test_mixed_mostly_cjk_splits(self):
        # 3 CJK + 1 latin = 75% CJK → splits
        result = _split_cjk_word("愛你A哦", 0.0, 1.0)
        assert len(result) == 4

    def test_mixed_mostly_latin_no_split(self):
        # 1 CJK + 3 latin = 25% CJK → no split
        result = _split_cjk_word("abc愛", 0.0, 1.0)
        assert len(result) == 1

    def test_timing_continuity(self):
        result = _split_cjk_word("你好世界", 2.0, 4.0)
        for i in range(len(result) - 1):
            assert abs(result[i][2] - result[i + 1][1]) < 0.001


class TestGenerateKaraokeAssWithCjk:
    def test_cjk_words_get_per_char_kf(self):
        segments = [
            {
                "text": "紅塵作伴",
                "words": [
                    {"word": "紅塵作伴", "start": 1.0, "end": 2.2},
                ],
            }
        ]
        ass = generate_karaoke_ass(segments)
        # Should have 4 \kf tags (one per character), not 1
        kf_count = ass.count("\\kf")
        # 4 chars + 1 pad = 5, or 4 if no pad
        assert kf_count >= 4

    def test_english_words_unchanged(self):
        segments = [
            {
                "text": "hello world",
                "words": [
                    {"word": "hello", "start": 1.0, "end": 1.5},
                    {"word": "world", "start": 1.5, "end": 2.0},
                ],
            }
        ]
        ass = generate_karaoke_ass(segments)
        # 2 words + 1 pad = 3 kf tags
        assert "hello" in ass
        assert "world" in ass


class TestTwoLineLayout:
    def _two_line_segments(self):
        return [
            {
                "text": "第一行歌詞",
                "words": [
                    {"word": "第一行", "start": 5.0, "end": 6.0},
                    {"word": "歌詞", "start": 6.0, "end": 7.0},
                ],
            },
            {
                "text": "第二行歌詞",
                "words": [
                    {"word": "第二行", "start": 10.0, "end": 11.0},
                    {"word": "歌詞", "start": 11.0, "end": 12.0},
                ],
            },
        ]

    def test_has_active_style(self):
        ass = generate_karaoke_ass(self._two_line_segments())
        assert "Style: Active," in ass

    def test_has_preview_style(self):
        ass = generate_karaoke_ass(self._two_line_segments())
        assert "Style: Preview," in ass

    def test_active_line_has_pos_tag(self):
        ass = generate_karaoke_ass(self._two_line_segments())
        assert "\\pos(1920,1960)" in ass

    def test_preview_line_has_pos_tag(self):
        ass = generate_karaoke_ass(self._two_line_segments())
        assert "\\pos(1920,1760)" in ass

    def test_preview_shows_next_line_text(self):
        ass = generate_karaoke_ass(self._two_line_segments())
        # Preview of line 2 should appear during line 1
        preview_lines = [l for l in ass.splitlines() if ",Preview," in l]
        assert len(preview_lines) >= 1
        assert "第二行歌詞" in preview_lines[0]

    def test_last_line_has_no_preview(self):
        segs = self._two_line_segments()
        ass = generate_karaoke_ass(segs)
        # Only 1 preview (for line 2 during line 1), not 2
        preview_lines = [l for l in ass.splitlines() if ",Preview," in l]
        assert len(preview_lines) == 1

    def test_active_layer_higher_than_preview(self):
        ass = generate_karaoke_ass(self._two_line_segments())
        for line in ass.splitlines():
            if ",Active," in line:
                assert line.startswith("Dialogue: 1,")
            elif ",Preview," in line:
                assert line.startswith("Dialogue: 0,")

    def test_cream_amber_colors(self):
        ass = generate_karaoke_ass(self._two_line_segments())
        assert "&H00E0F3FA" in ass  # Cream white primary
        assert "&H007CA8E8" in ass  # Warm amber secondary

    def test_uses_droid_sans_fallback_font(self):
        ass = generate_karaoke_ass(self._two_line_segments())
        assert "DroidSansFallback" in ass


class TestFilterHallucinations:
    def _seg(self, text, start=1.0, end=3.0, no_speech_prob=0.0):
        return {"text": text, "start": start, "end": end, "no_speech_prob": no_speech_prob}

    def test_keeps_real_lyrics(self):
        segs = [self._seg("讓我們紅塵作伴")]
        assert len(_filter_whisper_hallucinations(segs)) == 1

    def test_removes_credit_keywords(self):
        segs = [self._seg("作詞：林夕"), self._seg("混音：someone")]
        assert len(_filter_whisper_hallucinations(segs)) == 0

    def test_removes_new_keywords(self):
        for kw in ["主唱", "演唱", "感謝觀看", "please subscribe"]:
            segs = [self._seg(kw)]
            assert len(_filter_whisper_hallucinations(segs)) == 0, f"Should filter: {kw}"

    def test_removes_music_symbols_only(self):
        segs = [self._seg("♪♫♪♫")]
        assert len(_filter_whisper_hallucinations(segs)) == 0

    def test_removes_repeated_short_phrase(self):
        segs = [self._seg("啦啦啦啦啦啦啦啦啦啦啦啦啦啦啦啦")]
        assert len(_filter_whisper_hallucinations(segs)) == 0

    def test_removes_end_marker(self):
        for text in ["The End", "end", "終", "完"]:
            segs = [self._seg(text)]
            assert len(_filter_whisper_hallucinations(segs)) == 0, f"Should filter: {text}"

    def test_removes_pure_numbers(self):
        segs = [self._seg("12345")]
        assert len(_filter_whisper_hallucinations(segs)) == 0

    def test_removes_high_no_speech_prob(self):
        segs = [self._seg("some text", no_speech_prob=0.45)]
        assert len(_filter_whisper_hallucinations(segs)) == 0

    def test_removes_single_char_short_duration(self):
        segs = [self._seg("啊", start=1.0, end=1.5)]
        assert len(_filter_whisper_hallucinations(segs)) == 0

    def test_keeps_single_char_long_duration(self):
        segs = [self._seg("啊", start=1.0, end=2.5)]
        assert len(_filter_whisper_hallucinations(segs)) == 1


def _ass_seconds(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def test_no_negative_duration_active_lines_on_overlap():
    """A line whose row is still busy past its own end must NOT be emitted with
    Start>End (which libass renders for zero frames -> the line silently vanishes)."""
    segments = [
        # seg0 occupies row active_y for ~6s
        {
            "words": [
                {"word": c, "start": j * 0.6, "end": j * 0.6 + 0.6}
                for j, c in enumerate("一二三四五六七八九十")
            ]
        },
        {"words": [{"word": "甲", "start": 0.1, "end": 0.4}]},
        # seg2 lands on the same row (active_y) but is short + early -> used to get Start>End
        {"words": [{"word": "乙", "start": 0.2, "end": 0.5}]},
    ]
    ass = generate_karaoke_ass(segments, timing_offset=0.0)
    active = re.findall(r"^Dialogue:\s*\d+,([^,]+),([^,]+),Active,", ass, re.M)
    assert active, "expected Active dialogue lines"
    for start, end in active:
        assert _ass_seconds(start) < _ass_seconds(
            end
        ), f"negative/zero-duration Active line: {start} >= {end}"


def _chorus_segs():
    # 5 consecutive identical chorus lines (legitimate in CJK pop)
    return [
        {"text": "啦啦啦", "start": i * 3.0, "end": i * 3.0 + 2.0, "no_speech_prob": 0.0}
        for i in range(5)
    ]


def test_aligned_path_keeps_repeated_chorus_lines():
    kept = _filter_whisper_hallucinations(_chorus_segs(), online_aligned=True)
    assert len(kept) == 5  # all repeated chorus lines preserved on the aligned path


def test_aligned_path_keeps_long_lines():
    long_seg = [{"text": "間奏後的長句", "start": 0.0, "end": 25.0, "no_speech_prob": 0.0}]
    assert len(_filter_whisper_hallucinations(long_seg, online_aligned=True)) == 1


def test_raw_whisper_path_still_dedupes_and_drops_long():
    # default online_aligned=False keeps the existing raw-Whisper behavior
    assert len(_filter_whisper_hallucinations(_chorus_segs())) < 5  # adjacent-dup dedup
    long_seg = [{"text": "x", "start": 0.0, "end": 25.0, "no_speech_prob": 0.0}]
    assert len(_filter_whisper_hallucinations(long_seg)) == 0  # >20s dropped


def test_vocal_separator_uses_online_aligned_filter():
    vs = os.path.join(
        os.path.dirname(__file__), "..", "..", "pikaraoke", "lib", "vocal_separator.py"
    )
    with open(vs, encoding="utf-8") as f:
        src = f.read()
    assert "_filter_whisper_hallucinations(aligned, online_aligned=True)" in src


def test_aligned_path_keeps_5plus_repeat_chorus():
    """An onomatopoeic chorus repeated 5+ times (啦啦啦啦啦 / la la la la la) matches the
    \\1{3,} hallucination regex; on the online-aligned path it is a real lyric -> must survive."""
    zh = [{"text": "啦啦啦啦啦", "start": 0.0, "end": 3.0, "no_speech_prob": 0.0}]
    assert len(_filter_whisper_hallucinations(zh, online_aligned=True)) == 1
    en = [{"text": "la la la la la", "start": 0.0, "end": 3.0, "no_speech_prob": 0.0}]
    assert len(_filter_whisper_hallucinations(en, online_aligned=True)) == 1


def test_aligned_path_keeps_line_with_credit_keyword_substring():
    """An online lyric line containing a credit keyword as a substring (演唱) must survive on
    the aligned path -- online lyrics are already credit-filtered upstream in _search_online_lyrics.
    """
    segs = [{"text": "我演唱著我們的歌", "start": 0.0, "end": 3.0, "no_speech_prob": 0.0}]
    assert len(_filter_whisper_hallucinations(segs, online_aligned=True)) == 1


def test_raw_path_still_drops_5plus_repeat_and_credit_keyword():
    """Raw Whisper output keeps the aggressive filters: a 5+ repeat phrase and a clear credit
    line are still dropped when online_aligned is False (the default)."""
    rep = [{"text": "啦啦啦啦啦", "start": 0.0, "end": 3.0, "no_speech_prob": 0.0}]
    assert len(_filter_whisper_hallucinations(rep)) == 0
    credit = [{"text": "作詞 林夕", "start": 0.0, "end": 3.0, "no_speech_prob": 0.0}]
    assert len(_filter_whisper_hallucinations(credit)) == 0


def test_aligned_path_still_drops_junk_punctuation_and_numbers():
    """Junk lines (punctuation/symbol-only, pure numbers) are never sung lyrics, so they are
    dropped on BOTH paths, including online-aligned."""
    junk = [
        {"text": "♪♪♪", "start": 0.0, "end": 3.0, "no_speech_prob": 0.0},
        {"text": "123", "start": 4.0, "end": 6.0, "no_speech_prob": 0.0},
    ]
    assert len(_filter_whisper_hallucinations(junk, online_aligned=True)) == 0


def test_preview_lead_capped_across_instrumental_gap():
    """A long instrumental gap must not freeze the gray preview line for tens of seconds."""
    segments = [
        {
            "words": [
                {"word": c, "start": j * 0.5, "end": j * 0.5 + 0.5} for j, c in enumerate("第一行")
            ]
        },
        # next line starts 40s later (instrumental break)
        {
            "words": [
                {"word": c, "start": 40.0 + j * 0.5, "end": 40.0 + j * 0.5 + 0.5}
                for j, c in enumerate("第二行")
            ]
        },
    ]
    ass = generate_karaoke_ass(segments, timing_offset=0.0)
    previews = re.findall(r"^Dialogue:\s*\d+,([^,]+),([^,]+),Preview,", ass, re.M)
    assert previews, "expected a Preview line"
    for start, end in previews:
        assert _ass_seconds(end) - _ass_seconds(start) <= 6.01  # PREVIEW_LEAD + epsilon


def test_preview_derives_text_from_words_when_text_key_absent():
    """A words-only segment (no 'text' key) must still produce a Preview line for the next row."""
    segments = [
        {
            "words": [
                {"word": c, "start": j * 0.5, "end": j * 0.5 + 0.5} for j, c in enumerate("甲乙")
            ]
        },
        {
            "words": [
                {"word": c, "start": 2.0 + j * 0.5, "end": 2.0 + j * 0.5 + 0.5}
                for j, c in enumerate("丙丁")
            ]
        },
    ]
    ass = generate_karaoke_ass(segments, timing_offset=0.0)
    previews = re.findall(r"Preview,,0,0,0,,\{[^}]*\}(.+)", ass)
    assert any("丙" in p for p in previews), "next words-only line must still be previewed"


def test_short_line_duration_is_clamped():
    """A 1-char line with an inflated Whisper end must not produce an over-long crawling fill."""
    segments = [{"words": [{"word": "喔", "start": 0.0, "end": 8.0}]}]  # 8s for one char
    ass = generate_karaoke_ass(segments, timing_offset=0.0)
    durs = [int(d) for d in re.findall(r"\\kf(\d+)", ass)]
    assert durs
    assert max(durs) <= 250  # clamped centiseconds, not 800


def test_format_ass_time_clamps_negative_to_zero():
    """Negative seconds must clamp to 0, not emit '-1:59:59.30' which libass cannot parse."""
    from pikaraoke.lib.karaoke_subtitle import _format_ass_time

    assert _format_ass_time(-0.7) == "0:00:00.00"
    assert _format_ass_time(-100.0) == "0:00:00.00"
    # Non-negative times are unaffected
    assert _format_ass_time(0.0) == "0:00:00.00"
    assert _format_ass_time(75.34) == "0:01:15.34"


def test_no_negative_timestamps_with_default_offset():
    """The default timing_offset=-0.7 shifts an early vocal onset below zero. Every emitted
    Start/End must stay >=0 and Start<End, or libass drops the opening lyric line(s)."""
    segments = [
        # first word at t=0 -> seg_start would be -0.7 under the default offset
        {
            "words": [
                {"word": c, "start": j * 0.3, "end": j * 0.3 + 0.3} for j, c in enumerate("早安你好世界")
            ]
        },
        {
            "words": [
                {"word": c, "start": 2.0 + j * 0.3, "end": 2.0 + j * 0.3 + 0.3}
                for j, c in enumerate("第二行歌詞")
            ]
        },
    ]
    ass = generate_karaoke_ass(segments)  # default timing_offset=-0.7
    times = re.findall(r"^Dialogue:\s*\d+,([^,]+),([^,]+),", ass, re.M)
    assert times, "expected Dialogue lines"
    for start, end in times:
        assert not start.startswith("-"), f"negative Start timestamp: {start}"
        assert not end.startswith("-"), f"negative End timestamp: {end}"
        assert _ass_seconds(start) >= 0.0
        assert _ass_seconds(start) < _ass_seconds(end)
