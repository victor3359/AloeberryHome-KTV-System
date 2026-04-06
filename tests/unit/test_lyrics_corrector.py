"""Unit tests for lyrics_corrector alignment functions."""

from __future__ import annotations

from pikaraoke.lib.lyrics_corrector import (
    _has_cjk,
    _interpolate_word_timing,
    align_online_with_whisper_timing,
)


class TestHasCjk:
    def test_chinese(self):
        assert _has_cjk("紅塵作伴")

    def test_japanese(self):
        assert _has_cjk("さくら")

    def test_korean(self):
        assert _has_cjk("사랑")

    def test_english(self):
        assert not _has_cjk("hello world")

    def test_mixed(self):
        assert _has_cjk("love愛")


class TestInterpolateWordTiming:
    def test_cjk_per_char(self):
        result = _interpolate_word_timing("紅塵作伴", 1.0, 3.0, is_cjk=True)
        assert len(result) == 4
        assert result[0]["word"] == "紅"
        assert result[3]["word"] == "伴"
        assert abs(result[0]["end"] - result[0]["start"] - 0.5) < 0.01

    def test_english_per_word(self):
        result = _interpolate_word_timing("hello beautiful world", 0.0, 3.0, is_cjk=False)
        assert len(result) == 3
        assert result[0]["word"] == "hello"

    def test_empty_text(self):
        result = _interpolate_word_timing("", 0.0, 1.0)
        assert len(result) == 1


class TestAlignOnlineWithWhisperTiming:
    def test_basic_alignment(self):
        online = [
            {"start": 10.0, "end": 14.0, "text": "讓我們紅塵作伴", "words": []},
        ]
        whisper = [
            {
                "start": 10.2,
                "end": 13.8,
                "text": "讓我門紅塵做伴",  # Whisper typos
                "words": [
                    {"word": "讓我門", "start": 10.2, "end": 11.5},
                    {"word": "紅塵", "start": 11.5, "end": 12.3},
                    {"word": "做伴", "start": 12.3, "end": 13.8},
                ],
            },
        ]
        result = align_online_with_whisper_timing(online, whisper, "zh")
        assert result is not None
        assert len(result) == 1
        assert result[0]["text"] == "讓我們紅塵作伴"  # Online text used
        assert len(result[0]["words"]) > 0  # Has word-level timing

    def test_returns_none_on_low_match(self):
        online = [
            {"start": 10.0, "end": 14.0, "text": "完全不同的歌詞", "words": []},
            {"start": 15.0, "end": 19.0, "text": "另一首歌的內容", "words": []},
            {"start": 20.0, "end": 24.0, "text": "第三行完全不同", "words": []},
        ]
        whisper = [
            {"start": 50.0, "end": 54.0, "text": "Totally different", "words": []},
        ]
        result = align_online_with_whisper_timing(online, whisper)
        assert result is None  # <30% match rate

    def test_interpolation_fallback(self):
        online = [
            {"start": 5.0, "end": 8.0, "text": "沒有對應的歌詞行", "words": []},
        ]
        whisper = []  # No Whisper segments
        result = align_online_with_whisper_timing(online, whisper)
        assert result is None  # No whisper = None

    def test_english_word_alignment(self):
        online = [
            {"start": 1.0, "end": 3.0, "text": "hello world", "words": []},
        ]
        whisper = [
            {
                "start": 1.1,
                "end": 2.9,
                "text": "hello world",
                "words": [
                    {"word": "hello", "start": 1.1, "end": 2.0},
                    {"word": "world", "start": 2.0, "end": 2.9},
                ],
            },
        ]
        result = align_online_with_whisper_timing(online, whisper, "en")
        assert result is not None
        assert result[0]["words"][0]["word"] == "hello"
        assert result[0]["words"][1]["word"] == "world"

    def test_empty_inputs(self):
        assert align_online_with_whisper_timing([], []) is None
        assert align_online_with_whisper_timing(None, []) is None
