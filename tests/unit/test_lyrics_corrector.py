"""Unit tests for lyrics_corrector alignment functions."""

from __future__ import annotations

from pikaraoke.lib.lyrics_corrector import (
    _correct_typos_with_online_lyrics,
    _estimate_global_offset,
    _has_cjk,
    _interpolate_word_timing,
    _is_credit_line,
    _map_chars_to_whisper_words,
    align_online_with_whisper_timing,
)


class TestMapCharsToWhisperWords:
    """The mapping must ANCHOR online chars on their true Whisper counterpart (edit-distance
    alignment), not zip by index -- a single Whisper insertion/deletion used to slide the whole
    rest of the line out of sync (the '字幕對不上' root cause)."""

    def test_anchors_past_extra_leading_whisper_char(self):
        # Whisper heard an extra leading 啊 not present in the online lyric.
        whisper_words = [
            {"word": "啊", "start": 9.5, "end": 10.0},
            {"word": "我", "start": 10.0, "end": 11.0},
            {"word": "愛", "start": 11.0, "end": 12.0},
            {"word": "你", "start": 12.0, "end": 12.5},
        ]
        result = _map_chars_to_whisper_words("我愛你", whisper_words, is_cjk=True)
        assert [r["word"] for r in result] == ["我", "愛", "你"]
        # Each online char inherits its TRUE whisper char timing, not the same-index char.
        assert abs(result[0]["start"] - 10.0) < 0.01  # 我 -> whisper 我@10.0 (NOT 啊@9.5)
        assert abs(result[1]["start"] - 11.0) < 0.01  # 愛
        assert abs(result[2]["start"] - 12.0) < 0.01  # 你

    def test_interpolates_online_only_chars_within_the_gap(self):
        # Online lyric has 真的 that Whisper dropped -> they must interpolate in the 我..愛 gap,
        # and 愛/你 must stay anchored on their real timing (no cascade).
        whisper_words = [
            {"word": "我", "start": 0.0, "end": 1.0},
            {"word": "愛", "start": 3.0, "end": 4.0},
            {"word": "你", "start": 4.0, "end": 5.0},
        ]
        result = _map_chars_to_whisper_words("我真的愛你", whisper_words, is_cjk=True)
        assert [r["word"] for r in result] == ["我", "真", "的", "愛", "你"]
        assert abs(result[0]["start"] - 0.0) < 0.01  # 我 anchored
        assert abs(result[3]["start"] - 3.0) < 0.01  # 愛 anchored (NOT pushed to excess)
        assert abs(result[4]["start"] - 4.0) < 0.01  # 你 anchored
        assert 1.0 <= result[1]["start"] < 3.0       # 真 in the gap
        assert 1.0 <= result[2]["start"] < 3.0       # 的 in the gap
        starts = [r["start"] for r in result]
        assert starts == sorted(starts)              # monotonic

    def test_leading_insertion_stays_monotonic_and_keeps_anchor(self):
        """Whisper missed the line's opening syllables (leading insertion). The online-only
        chars must NOT overrun the first anchored char's true timing (no backward fill)."""
        whisper_words = [
            {"word": "愛", "start": 2.0, "end": 3.0},
            {"word": "你", "start": 3.0, "end": 4.0},
        ]
        result = _map_chars_to_whisper_words("我真愛你", whisper_words, is_cjk=True)
        assert [r["word"] for r in result] == ["我", "真", "愛", "你"]
        for k in range(1, len(result)):
            # monotonic: no char starts before the previous char ends
            assert result[k]["start"] >= result[k - 1]["end"] - 1e-9
        ai = [r["word"] for r in result].index("愛")
        assert abs(result[ai]["start"] - 2.0) < 0.01  # 愛 keeps its TRUE anchor, not pushed later

    def test_contiguous_middle_insertion_stays_monotonic(self):
        """An online-only char between two contiguous Whisper chars (no time gap) must collapse
        to the boundary, not overrun the following anchor."""
        whisper_words = [
            {"word": "我", "start": 0.0, "end": 1.0},
            {"word": "愛", "start": 1.0, "end": 2.0},  # contiguous: no gap for the inserted char
        ]
        result = _map_chars_to_whisper_words("我嗯愛", whisper_words, is_cjk=True)
        assert [r["word"] for r in result] == ["我", "嗯", "愛"]
        for k in range(1, len(result)):
            assert result[k]["start"] >= result[k - 1]["end"] - 1e-9
        ai = [r["word"] for r in result].index("愛")
        assert abs(result[ai]["start"] - 1.0) < 0.01  # 愛 anchor preserved

    def test_trailing_excess_chars_still_extend_forward(self):
        """Online chars past the last Whisper char (trailing insertion) have no following anchor,
        so they should still extend forward with real duration (not collapse to a point)."""
        whisper_words = [
            {"word": "我", "start": 0.0, "end": 1.0},
            {"word": "愛", "start": 1.0, "end": 2.0},
        ]
        result = _map_chars_to_whisper_words("我愛你啊", whisper_words, is_cjk=True)
        assert [r["word"] for r in result] == ["我", "愛", "你", "啊"]
        # trailing 你/啊 get non-zero durations
        assert result[2]["end"] > result[2]["start"]
        assert result[3]["end"] > result[3]["start"]
        starts = [r["start"] for r in result]
        assert starts == sorted(starts)


class TestCorrectTyposNoCascade:
    def test_no_cascade_on_length_mismatch(self):
        """The fallback typo path must not cascade when online length != whisper length: an
        extra online char used to shift every subsequent char, corrupting a correct line."""
        whisper = [{
            "start": 1.0, "end": 4.0, "text": "我門紅塵做伴",
            "words": [
                {"word": "我門", "start": 1.0, "end": 2.0},
                {"word": "紅塵", "start": 2.0, "end": 3.0},
                {"word": "做伴", "start": 3.0, "end": 4.0},
            ],
        }]
        # Extra leading 啊 makes online longer than whisper; homophones 門->們, 做->作.
        online = [{"start": 1.0, "end": 4.0, "text": "啊我們紅塵作伴", "words": []}]
        result = _correct_typos_with_online_lyrics(whisper, online)
        text = "".join(w["word"] for seg in result for w in seg["words"])
        # Homophones corrected; extra 啊 NOT inserted; whisper structure preserved (no cascade).
        assert text == "我們紅塵作伴"

    def test_equal_length_homophone_still_corrected(self):
        whisper = [{
            "start": 1.0, "end": 4.0, "text": "我們紅塵做伴",
            "words": [
                {"word": "我們", "start": 1.0, "end": 2.0},
                {"word": "紅塵", "start": 2.0, "end": 3.0},
                {"word": "做伴", "start": 3.0, "end": 4.0},
            ],
        }]
        online = [{"start": 1.0, "end": 4.0, "text": "我們紅塵作伴", "words": []}]  # single homophone 做->作
        result = _correct_typos_with_online_lyrics(whisper, online)
        text = "".join(w["word"] for seg in result for w in seg["words"])
        assert text == "我們紅塵作伴"


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

    def test_global_offset_correction(self):
        """LRC is 25s ahead of MV — offset should be detected and corrected."""
        online = [
            {"start": 0.0, "end": 4.0, "text": "你在房間像幻燈片", "words": []},
            {"start": 5.0, "end": 9.0, "text": "你在我眼裡蔓延", "words": []},
        ]
        whisper = [
            {
                "start": 25.0, "end": 29.0, "text": "你在房間像幻燈片",
                "words": [{"word": "你在房間像幻燈片", "start": 25.0, "end": 29.0}],
            },
            {
                "start": 30.0, "end": 34.0, "text": "你在我眼裡蔓延",
                "words": [{"word": "你在我眼裡蔓延", "start": 30.0, "end": 34.0}],
            },
        ]
        result = align_online_with_whisper_timing(online, whisper, "zh")
        assert result is not None
        # After offset correction, online timestamps should align with Whisper
        assert result[0]["start"] > 20.0  # Should be near 25, not 0


class TestWrongSongRejection:
    @staticmethod
    def _segs(texts):
        return [
            {"start": i * 4.0, "end": i * 4.0 + 4.0, "text": t, "words": []}
            for i, t in enumerate(texts)
        ]

    @staticmethod
    def _whisper(texts):
        return [
            {
                "start": i * 4.0,
                "end": i * 4.0 + 4.0,
                "text": t,
                "words": [{"word": t, "start": i * 4.0, "end": i * 4.0 + 4.0}],
            }
            for i, t in enumerate(texts)
        ]

    def test_rejects_wrong_song_lyrics(self):
        """A wrong-song LRC whose lines never text-match the Whisper transcript must be rejected.
        The old gate only checked word-PRESENCE in a time window, so it accepted wrong text."""
        online = self._segs(
            ["完全不同的歌詞甲", "完全不同的歌詞乙", "完全不同的歌詞丙", "完全不同的歌詞丁", "完全不同的歌詞戊"]
        )
        whisper = self._whisper(
            ["天空很藍海洋很寬", "微風輕拂過臉龐", "我想起你的笑容", "在那個夏天午後", "時光匆匆流逝"]
        )
        assert align_online_with_whisper_timing(online, whisper, "zh") is None

    def test_accepts_matching_song_with_minor_diffs(self):
        online = self._segs(
            ["天空很藍海洋很寬", "微風輕拂過臉龐", "我想起你的笑容", "在那個夏天午後", "時光匆匆流逝"]
        )
        whisper = self._whisper(
            ["天空很藍海洋很寬", "微風輕撫過臉龐", "我想起你的笑容", "在那個夏天午後", "時光匆匆流逝"]
        )
        result = align_online_with_whisper_timing(online, whisper, "zh")
        assert result is not None
        assert len(result) == 5


class TestEstimateGlobalOffset:
    def test_detects_offset(self):
        online = [
            {"start": 0.0, "text": "你在房間像幻燈片"},
            {"start": 5.0, "text": "你在我眼裡蔓延"},
        ]
        whisper = [
            {"start": 25.0, "text": "你在房間像幻燈片"},
            {"start": 30.0, "text": "你在我眼裡蔓延"},
        ]
        offset = _estimate_global_offset(online, whisper)
        assert abs(offset - (-25.0)) < 1.0

    def test_no_offset_when_aligned(self):
        online = [{"start": 10.0, "text": "hello world"}]
        whisper = [{"start": 10.5, "text": "hello world"}]
        offset = _estimate_global_offset(online, whisper)
        assert abs(offset) < 2.0

    def test_no_match_returns_zero(self):
        online = [{"start": 0.0, "text": "完全不同"}]
        whisper = [{"start": 50.0, "text": "totally different"}]
        assert _estimate_global_offset(online, whisper) == 0.0


class TestIsCreditLine:
    def test_chinese_credits(self):
        assert _is_credit_line("作曲 : Lee Wei Song")
        assert _is_credit_line("詞曲 李宗盛")
        assert _is_credit_line("作詞：林夕")

    def test_english_credits(self):
        assert _is_credit_line("Lyrics by Someone")
        assert _is_credit_line("Produced by XYZ")

    def test_real_lyrics_not_credit(self):
        assert not _is_credit_line("你在房間像幻燈片")
        assert not _is_credit_line("hello world")
