"""Unit tests for karaoke_subtitle module."""

from __future__ import annotations

from pikaraoke.lib.karaoke_subtitle import (
    _filter_whisper_hallucinations,
    _is_cjk_char,
    _split_cjk_word,
    generate_karaoke_ass,
)


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
