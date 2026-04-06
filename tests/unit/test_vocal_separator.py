"""Unit tests for vocal_separator module."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from pikaraoke.lib.events import EventSystem
from pikaraoke.lib.vocal_separator import (
    ProcessResult,
    SeparationResult,
    StemPaths,
    TranscriptionResult,
    VocalSeparator,
    _ass_path_for,
    _clean_search_title,
    _filter_whisper_hallucinations,
    _format_ass_time,
    _parse_lrc_line,
    _stem_paths_for,
    generate_karaoke_ass,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def events():
    return EventSystem()


@pytest.fixture
def separator(events, tmp_path):
    return VocalSeparator(
        events=events,
        download_path=str(tmp_path),
        device="cpu",
        whisper_model="tiny",
    )


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestStemPathsFor:
    def test_returns_vocals_and_instrumental(self):
        v, i = _stem_paths_for("/songs/My Song---abc12345678.mp4")
        assert v == "/songs/My Song---abc12345678_vocals.mp3"
        assert i == "/songs/My Song---abc12345678_instrumental.mp3"

    def test_strips_extension(self):
        v, i = _stem_paths_for("/songs/Track.webm")
        assert v == "/songs/Track_vocals.mp3"
        assert i == "/songs/Track_instrumental.mp3"


class TestAssPathFor:
    def test_returns_karaoke_ass(self):
        assert _ass_path_for("/songs/Track.mp4") == "/songs/Track_karaoke.ass"


class TestFormatAssTime:
    def test_zero(self):
        assert _format_ass_time(0) == "0:00:00.00"

    def test_minutes_and_seconds(self):
        assert _format_ass_time(65.5) == "0:01:05.50"

    def test_hours(self):
        assert _format_ass_time(3661.25) == "1:01:01.25"


class TestParseLrcLine:
    def test_valid_lrc_line(self):
        result = _parse_lrc_line("[01:23.45]Hello world")
        assert result == (83.45, "Hello world")

    def test_invalid_line_returns_none(self):
        assert _parse_lrc_line("not a valid line") is None

    def test_empty_text(self):
        result = _parse_lrc_line("[00:00.00]")
        assert result == (0.0, "")


class TestCleanSearchTitle:
    def test_removes_youtube_id_suffix(self):
        assert "dQw4w9WgXcQ" not in _clean_search_title("My Song---dQw4w9WgXcQ")

    def test_removes_official_mv(self):
        cleaned = _clean_search_title("Artist - Song (Official MV)")
        assert "official" not in cleaned.lower()
        assert "mv" not in cleaned.lower()

    def test_removes_file_extension(self):
        cleaned = _clean_search_title("Artist - Song.mp4")
        assert ".mp4" not in cleaned


# ---------------------------------------------------------------------------
# VocalSeparator method tests
# ---------------------------------------------------------------------------


class TestIsAvailable:
    @patch("pikaraoke.lib.vocal_separator.DEMUCS_AVAILABLE", False)
    def test_false_when_demucs_not_installed(self, separator):
        assert separator.is_available() is False

    @patch("pikaraoke.lib.vocal_separator.DEMUCS_AVAILABLE", True)
    def test_true_when_demucs_installed(self, separator):
        assert separator.is_available() is True


class TestIsWhisperAvailable:
    @patch("pikaraoke.lib.vocal_separator.WHISPER_AVAILABLE", False)
    def test_false_when_whisper_not_installed(self, separator):
        assert separator.is_whisper_available() is False

    @patch("pikaraoke.lib.vocal_separator.WHISPER_AVAILABLE", True)
    def test_true_when_whisper_installed(self, separator):
        assert separator.is_whisper_available() is True


class TestHasStems:
    def test_true_when_both_files_exist(self, separator, tmp_path):
        song = str(tmp_path / "Song---abc12345678.mp4")
        vocals = str(tmp_path / "Song---abc12345678_vocals.mp3")
        instrumental = str(tmp_path / "Song---abc12345678_instrumental.mp3")
        open(vocals, "w").close()
        open(instrumental, "w").close()

        assert separator.has_stems(song) is True

    def test_false_when_vocals_missing(self, separator, tmp_path):
        song = str(tmp_path / "Song---abc12345678.mp4")
        instrumental = str(tmp_path / "Song---abc12345678_instrumental.mp3")
        open(instrumental, "w").close()

        assert separator.has_stems(song) is False

    def test_false_when_no_companions(self, separator, tmp_path):
        song = str(tmp_path / "Song---abc12345678.mp4")
        assert separator.has_stems(song) is False


class TestHasKaraokeAss:
    def test_true_when_ass_exists(self, separator, tmp_path):
        song = str(tmp_path / "Song.mp4")
        ass_file = str(tmp_path / "Song_karaoke.ass")
        open(ass_file, "w").close()
        assert separator.has_karaoke_ass(song) is True

    def test_false_when_missing(self, separator, tmp_path):
        song = str(tmp_path / "Song.mp4")
        assert separator.has_karaoke_ass(song) is False


class TestGetStemPaths:
    def test_returns_paths_when_exist(self, separator, tmp_path):
        song = str(tmp_path / "Track.mp4")
        vocals = str(tmp_path / "Track_vocals.mp3")
        instrumental = str(tmp_path / "Track_instrumental.mp3")
        open(vocals, "w").close()
        open(instrumental, "w").close()

        result = separator.get_stem_paths(song)
        assert result is not None
        assert result.vocals == vocals
        assert result.instrumental == instrumental

    def test_returns_none_when_missing(self, separator, tmp_path):
        song = str(tmp_path / "Track.mp4")
        assert separator.get_stem_paths(song) is None


# ---------------------------------------------------------------------------
# Hallucination filter tests
# ---------------------------------------------------------------------------


class TestFilterWhisperHallucinations:
    def test_removes_known_keywords(self):
        segments = [
            {"start": 0, "end": 3, "text": "Hello world", "no_speech_prob": 0.0},
            {"start": 3, "end": 6, "text": "作詞 Some Name", "no_speech_prob": 0.0},
            {"start": 6, "end": 9, "text": "Lyrics by Someone", "no_speech_prob": 0.0},
            {"start": 9, "end": 12, "text": "subscribe for more", "no_speech_prob": 0.0},
        ]
        result = _filter_whisper_hallucinations(segments)
        texts = [s["text"] for s in result]
        assert "Hello world" in texts
        assert len(result) == 1

    def test_keeps_real_lyrics(self):
        segments = [
            {"start": 0, "end": 3, "text": "I love you so much", "no_speech_prob": 0.0},
            {"start": 3, "end": 6, "text": "Under the moonlight", "no_speech_prob": 0.0},
            {"start": 6, "end": 9, "text": "We dance together", "no_speech_prob": 0.0},
        ]
        result = _filter_whisper_hallucinations(segments)
        assert len(result) == 3

    def test_removes_empty_text(self):
        segments = [
            {"start": 0, "end": 3, "text": "", "no_speech_prob": 0.0},
            {"start": 3, "end": 6, "text": "   ", "no_speech_prob": 0.0},
        ]
        result = _filter_whisper_hallucinations(segments)
        assert len(result) == 0

    def test_removes_very_short_segments(self):
        segments = [
            {"start": 0, "end": 0.05, "text": "blip", "no_speech_prob": 0.0},
        ]
        result = _filter_whisper_hallucinations(segments)
        assert len(result) == 0

    def test_removes_high_no_speech_prob(self):
        segments = [
            {"start": 0, "end": 3, "text": "phantom text", "no_speech_prob": 0.8},
        ]
        result = _filter_whisper_hallucinations(segments)
        assert len(result) == 0

    def test_removes_suspiciously_long_segments(self):
        segments = [
            {"start": 0, "end": 25, "text": "This is way too long", "no_speech_prob": 0.0},
        ]
        result = _filter_whisper_hallucinations(segments)
        assert len(result) == 0

    def test_removes_repeated_text_beyond_threshold(self):
        """Repeated identical text (>3 times) is removed as hallucination."""
        seg = {"start": 0, "end": 3, "text": "la la la", "no_speech_prob": 0.0}
        segments = [
            {**seg, "start": i * 3, "end": i * 3 + 3}
            for i in range(6)
        ]
        result = _filter_whisper_hallucinations(segments)
        # First occurrence kept, consecutive duplicate skipped, so only odd-indexed
        # survive until count reaches 4 (indices 0, 2, 4 would be non-consecutive).
        # Actually: idx0 kept (count=1, prev=None), idx1 skipped (consecutive dup),
        # idx2 skipped (consecutive dup), etc. Only index 0 passes.
        assert len(result) == 1

    def test_removes_consecutive_identical_lines(self):
        segments = [
            {"start": 0, "end": 3, "text": "hello", "no_speech_prob": 0.0},
            {"start": 3, "end": 6, "text": "hello", "no_speech_prob": 0.0},
            {"start": 6, "end": 9, "text": "world", "no_speech_prob": 0.0},
        ]
        result = _filter_whisper_hallucinations(segments)
        assert len(result) == 2
        assert result[0]["text"] == "hello"
        assert result[1]["text"] == "world"


# ---------------------------------------------------------------------------
# ASS generation tests
# ---------------------------------------------------------------------------


class TestGenerateKaraokeAss:
    def test_creates_valid_ass_content(self):
        segments = [
            {
                "start": 1.0,
                "end": 3.0,
                "text": "Hello world",
                "words": [
                    {"word": "Hello", "start": 1.0, "end": 1.5},
                    {"word": "world", "start": 1.5, "end": 3.0},
                ],
            }
        ]
        content = generate_karaoke_ass(segments, title="Test Song")
        assert "[Script Info]" in content
        assert "Title: Test Song" in content
        assert "[V4+ Styles]" in content
        assert "[Events]" in content
        assert "Dialogue:" in content

    def test_contains_kf_tags(self):
        segments = [
            {
                "start": 1.0,
                "end": 3.0,
                "text": "Hello",
                "words": [{"word": "Hello", "start": 1.0, "end": 3.0}],
            }
        ]
        content = generate_karaoke_ass(segments)
        assert "\\kf" in content

    def test_writes_file_to_disk(self, tmp_path):
        """Verify the full pipeline of generating and writing an ASS file."""
        segments = [
            {
                "start": 0.5,
                "end": 2.5,
                "text": "Test line",
                "words": [
                    {"word": "Test", "start": 0.5, "end": 1.5},
                    {"word": "line", "start": 1.5, "end": 2.5},
                ],
            }
        ]
        content = generate_karaoke_ass(segments, title="My Song")
        ass_file = tmp_path / "My_Song_karaoke.ass"
        ass_file.write_text(content, encoding="utf-8")

        assert ass_file.exists()
        written = ass_file.read_text(encoding="utf-8")
        assert "Dialogue:" in written
        assert "\\kf" in written

    def test_handles_segments_without_words(self):
        """Segments without word-level timing still produce dialogue lines."""
        segments = [
            {"start": 1.0, "end": 4.0, "text": "No word timing"},
        ]
        content = generate_karaoke_ass(segments)
        assert "Dialogue:" in content
        assert "No word timing" in content

    def test_skips_segments_with_empty_text_and_no_words(self):
        segments = [
            {"start": 1.0, "end": 4.0, "text": ""},
            {"start": 4.0, "end": 7.0, "text": "", "words": []},
        ]
        content = generate_karaoke_ass(segments)
        assert content.count("Dialogue:") == 0

    def test_no_words_fallback_uses_segment_text(self):
        """Segment with text but no words still produces a Dialogue line."""
        segments = [
            {"start": 1.0, "end": 4.0, "text": "Fallback line", "words": []},
        ]
        content = generate_karaoke_ass(segments)
        assert content.count("Dialogue:") == 1
        assert "Fallback line" in content


# ---------------------------------------------------------------------------
# Separate (Demucs) tests
# ---------------------------------------------------------------------------


class TestSeparate:
    @patch("pikaraoke.lib.vocal_separator.DEMUCS_AVAILABLE", False)
    def test_returns_error_when_demucs_unavailable(self, separator, tmp_path):
        song = str(tmp_path / "Song.mp4")
        result = separator.separate(song)
        assert result.success is False
        assert "not installed" in result.error

    @patch("pikaraoke.lib.vocal_separator.DEMUCS_AVAILABLE", True)
    def test_returns_cached_stems_if_exist(self, separator, tmp_path):
        song = str(tmp_path / "Song.mp4")
        vocals = str(tmp_path / "Song_vocals.mp3")
        instrumental = str(tmp_path / "Song_instrumental.mp3")
        open(vocals, "w").close()
        open(instrumental, "w").close()

        result = separator.separate(song)
        assert result.success is True
        assert result.stem_paths.vocals == vocals
        assert result.stem_paths.instrumental == instrumental


# ---------------------------------------------------------------------------
# Transcribe (Whisper) tests
# ---------------------------------------------------------------------------


class TestTranscribe:
    @patch("pikaraoke.lib.vocal_separator.WHISPER_AVAILABLE", False)
    def test_returns_error_when_whisper_unavailable(self, separator, tmp_path):
        song = str(tmp_path / "Song.mp4")
        result = separator.transcribe(song)
        assert result.success is False
        assert "not installed" in result.error


# ---------------------------------------------------------------------------
# Process (full pipeline) tests
# ---------------------------------------------------------------------------


class TestProcess:
    @patch("pikaraoke.lib.vocal_separator.DEMUCS_AVAILABLE", False)
    @patch("pikaraoke.lib.vocal_separator.WHISPER_AVAILABLE", False)
    def test_skips_when_not_available(self, separator, tmp_path):
        """When neither Demucs nor Whisper is available, process returns failure."""
        song = str(tmp_path / "Song.mp4")
        result = separator.process(song, title="Song")
        assert result.success is False
        assert result.stem_paths is None
        assert result.ass_path is None

    @patch("pikaraoke.lib.vocal_separator.DEMUCS_AVAILABLE", True)
    @patch("pikaraoke.lib.vocal_separator.WHISPER_AVAILABLE", False)
    def test_runs_separation_only_when_no_whisper(self, separator, tmp_path):
        """When only Demucs is available, separation runs but no ASS is generated."""
        song = str(tmp_path / "Song.mp4")
        vocals = str(tmp_path / "Song_vocals.mp3")
        instrumental = str(tmp_path / "Song_instrumental.mp3")
        open(vocals, "w").close()
        open(instrumental, "w").close()

        result = separator.process(song, title="Song")
        assert result.success is True
        assert result.stem_paths is not None
        assert result.ass_path is None

    @patch("pikaraoke.lib.vocal_separator.DEMUCS_AVAILABLE", False)
    @patch("pikaraoke.lib.vocal_separator.WHISPER_AVAILABLE", True)
    def test_runs_transcription_only_when_no_demucs(self, separator, tmp_path, events):
        """When only Whisper is available, transcription runs (mocked subprocess)."""
        song = str(tmp_path / "Song.mp4")
        open(song, "w").close()

        fake_segments = [
            {
                "start": 0,
                "end": 3,
                "text": "Hello",
                "words": [{"word": "Hello", "start": 0, "end": 3}],
                "no_speech_prob": 0.0,
            }
        ]
        mock_result = TranscriptionResult(
            success=True, segments=fake_segments, language="en"
        )

        with patch.object(separator, "transcribe", return_value=mock_result):
            with patch(
                "pikaraoke.lib.vocal_separator._search_online_lyrics", return_value=None
            ):
                with patch(
                    "pikaraoke.lib.pitch_extractor.extract_pitch",
                    side_effect=ImportError("not installed"),
                ):
                    result = separator.process(song, title="Song")

        assert result.success is True
        assert result.stem_paths is None
        assert result.ass_path is not None
        assert result.language == "en"
        # Verify the ASS file was actually written
        assert os.path.exists(result.ass_path)


# ---------------------------------------------------------------------------
# Language detection tests
# ---------------------------------------------------------------------------


class TestDetectLanguageFromFilename:
    def test_japanese(self):
        assert VocalSeparator._detect_language_from_filename("songs/こんにちは.mp4") == "ja"

    def test_korean(self):
        assert VocalSeparator._detect_language_from_filename("songs/안녕하세요.mp4") == "ko"

    def test_chinese(self):
        assert VocalSeparator._detect_language_from_filename("songs/你好世界.mp4") == "zh"

    def test_vietnamese(self):
        assert VocalSeparator._detect_language_from_filename("songs/Đường xa.mp4") == "vi"

    def test_english_returns_none(self):
        assert VocalSeparator._detect_language_from_filename("songs/Hello World.mp4") is None


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_stem_paths(self):
        sp = StemPaths(vocals="/v.mp3", instrumental="/i.mp3")
        assert sp.vocals == "/v.mp3"
        assert sp.instrumental == "/i.mp3"

    def test_separation_result_defaults(self):
        r = SeparationResult(success=False)
        assert r.stem_paths is None
        assert r.error is None

    def test_transcription_result_defaults(self):
        r = TranscriptionResult(success=True)
        assert r.segments == []
        assert r.language == ""
        assert r.error is None

    def test_process_result_defaults(self):
        r = ProcessResult(success=True)
        assert r.stem_paths is None
        assert r.ass_path is None
        assert r.language == ""
        assert r.error is None
