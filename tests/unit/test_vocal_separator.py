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

    def test_millisecond_fraction(self):
        # P1-4: a 3-digit fraction is milliseconds, not centiseconds. Dividing by 100
        # regardless of width shifted every ms-LRC line (e.g. NetEase) by up to ~9.9s.
        result = _parse_lrc_line("[01:23.456]Hello world")
        assert result == (83.456, "Hello world")

    def test_decisecond_fraction(self):
        # A 1-digit fraction is tenths of a second.
        result = _parse_lrc_line("[01:23.4]Hello world")
        assert result == (83.4, "Hello world")


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
        with open(vocals, "w") as f:
            f.write("v")
        with open(instrumental, "w") as f:
            f.write("i")

        assert separator.has_stems(song) is True

    def test_false_when_vocals_missing(self, separator, tmp_path):
        song = str(tmp_path / "Song---abc12345678.mp4")
        instrumental = str(tmp_path / "Song---abc12345678_instrumental.mp3")
        with open(instrumental, "w") as f:
            f.write("i")

        assert separator.has_stems(song) is False

    def test_false_when_no_companions(self, separator, tmp_path):
        song = str(tmp_path / "Song---abc12345678.mp4")
        assert separator.has_stems(song) is False


class TestHasKaraokeAss:
    def test_true_when_ass_has_content(self, separator, tmp_path):
        song = str(tmp_path / "Song.mp4")
        ass_file = str(tmp_path / "Song_karaoke.ass")
        with open(ass_file, "w") as f:
            f.write("[Script Info]\n")
        assert separator.has_karaoke_ass(song) is True

    def test_false_when_missing(self, separator, tmp_path):
        song = str(tmp_path / "Song.mp4")
        assert separator.has_karaoke_ass(song) is False

    def test_false_when_zero_byte(self, separator, tmp_path):
        """P1-8: a 0-byte ASS is a crashed-run artifact. Treating it as present made
        ensure_subtitles_async's os.path.exists gate skip the backfill forever, so the song
        served an empty subtitle file with no path to repair. Match process()'s own reuse
        check, which uses _is_nonempty_file."""
        song = str(tmp_path / "Song.mp4")
        open(str(tmp_path / "Song_karaoke.ass"), "w").close()  # 0 bytes
        assert separator.has_karaoke_ass(song) is False


class TestGetStemPaths:
    def test_returns_paths_when_exist(self, separator, tmp_path):
        song = str(tmp_path / "Track.mp4")
        vocals = str(tmp_path / "Track_vocals.mp3")
        instrumental = str(tmp_path / "Track_instrumental.mp3")
        with open(vocals, "w") as f:
            f.write("v")
        with open(instrumental, "w") as f:
            f.write("i")

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
        segments = [{**seg, "start": i * 3, "end": i * 3 + 3} for i in range(6)]
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
        with open(vocals, "w") as f:
            f.write("v")
        with open(instrumental, "w") as f:
            f.write("i")

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
        with open(vocals, "w") as f:
            f.write("v")
        with open(instrumental, "w") as f:
            f.write("i")

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
        mock_result = TranscriptionResult(success=True, segments=fake_segments, language="en")

        with patch.object(separator, "transcribe", return_value=mock_result):
            with patch("pikaraoke.lib.vocal_separator._search_online_lyrics", return_value=None):
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

    def test_process_result_used_stems_default(self):
        """ProcessResult exposes whether real separated stems were used."""
        r = ProcessResult(success=True)
        assert r.used_stems is False


# ---------------------------------------------------------------------------
# Robustness fixes
# ---------------------------------------------------------------------------


class TestHasStemsZeroByte:
    """Fix 2: a 0-byte stem (crashed run) must not count as present."""

    def test_false_when_vocals_empty(self, separator, tmp_path):
        song = str(tmp_path / "Song.mp4")
        open(str(tmp_path / "Song_vocals.mp3"), "w").close()  # 0 bytes
        with open(str(tmp_path / "Song_instrumental.mp3"), "w") as f:
            f.write("data")
        assert separator.has_stems(song) is False

    def test_false_when_instrumental_empty(self, separator, tmp_path):
        song = str(tmp_path / "Song.mp4")
        with open(str(tmp_path / "Song_vocals.mp3"), "w") as f:
            f.write("data")
        open(str(tmp_path / "Song_instrumental.mp3"), "w").close()  # 0 bytes
        assert separator.has_stems(song) is False

    def test_true_when_both_non_empty(self, separator, tmp_path):
        song = str(tmp_path / "Song.mp4")
        for suffix in ("_vocals.mp3", "_instrumental.mp3"):
            with open(str(tmp_path / f"Song{suffix}"), "w") as f:
                f.write("data")
        assert separator.has_stems(song) is True

    def test_get_stem_paths_none_when_empty(self, separator, tmp_path):
        song = str(tmp_path / "Song.mp4")
        open(str(tmp_path / "Song_vocals.mp3"), "w").close()  # 0 bytes
        with open(str(tmp_path / "Song_instrumental.mp3"), "w") as f:
            f.write("data")
        assert separator.get_stem_paths(song) is None


class TestSeparateAtomicRename:
    """Fix 1: stale stem target must not break separation (os.replace overwrite)."""

    @patch("pikaraoke.lib.vocal_separator.DEMUCS_AVAILABLE", True)
    def test_overwrites_stale_targets(self, separator, tmp_path):
        song = str(tmp_path / "Song.mp4")
        # Stale (truncated/empty) targets from a crashed run.
        open(str(tmp_path / "Song_vocals.mp3"), "w").close()
        open(str(tmp_path / "Song_instrumental.mp3"), "w").close()

        # Demucs "output" dir with fresh stems.
        demucs_dir = tmp_path / "htdemucs" / "Song"
        demucs_dir.mkdir(parents=True)
        (demucs_dir / "vocals.mp3").write_text("fresh-vocals")
        (demucs_dir / "no_vocals.mp3").write_text("fresh-instrumental")

        completed = MagicMock(returncode=0, stderr="", stdout="")
        with patch("pikaraoke.lib.vocal_separator.subprocess.run", return_value=completed):
            result = separator.separate(song)

        assert result.success is True, result.error
        assert os.path.exists(result.stem_paths.vocals)
        # The fresh content replaced the stale 0-byte file.
        with open(result.stem_paths.vocals) as f:
            assert f.read() == "fresh-vocals"


class TestProcessDegradedSeparation:
    """Fix 3: a degraded run (no real stems) must be observable."""

    @patch("pikaraoke.lib.vocal_separator.DEMUCS_AVAILABLE", True)
    @patch("pikaraoke.lib.vocal_separator.WHISPER_AVAILABLE", True)
    def test_records_degraded_when_separation_fails(self, separator, tmp_path, events):
        song = str(tmp_path / "Song.mp4")
        open(song, "w").close()

        notes: list = []
        events.on("notification", lambda *a, **k: notes.append(a))

        fake_segments = [
            {
                "start": 0,
                "end": 3,
                "text": "Hello",
                "words": [{"word": "Hello", "start": 0, "end": 3}],
                "no_speech_prob": 0.0,
            }
        ]
        with patch.object(
            separator,
            "separate",
            return_value=SeparationResult(success=False, error="boom"),
        ):
            with patch.object(
                separator,
                "transcribe",
                return_value=TranscriptionResult(
                    success=True, segments=fake_segments, language="en"
                ),
            ):
                with patch(
                    "pikaraoke.lib.vocal_separator._search_online_lyrics",
                    return_value=None,
                ):
                    with patch(
                        "pikaraoke.lib.pitch_extractor.extract_pitch",
                        side_effect=ImportError("nope"),
                    ):
                        result = separator.process(song, title="Song")

        assert result.success is True
        assert result.ass_path is not None
        # The degraded state is observable on the result...
        assert result.used_stems is False
        # ...and via a user-facing notification.
        assert any(notes), "expected a degraded-quality notification"

    @patch("pikaraoke.lib.vocal_separator.DEMUCS_AVAILABLE", True)
    @patch("pikaraoke.lib.vocal_separator.WHISPER_AVAILABLE", True)
    def test_used_stems_true_when_separation_succeeds(self, separator, tmp_path, events):
        song = str(tmp_path / "Song.mp4")
        open(song, "w").close()
        vocals = str(tmp_path / "Song_vocals.mp3")
        with open(vocals, "w") as f:
            f.write("v")

        fake_segments = [
            {
                "start": 0,
                "end": 3,
                "text": "Hello",
                "words": [{"word": "Hello", "start": 0, "end": 3}],
                "no_speech_prob": 0.0,
            }
        ]
        stems = StemPaths(vocals=vocals, instrumental=str(tmp_path / "Song_instrumental.mp3"))
        with patch.object(
            separator,
            "separate",
            return_value=SeparationResult(success=True, stem_paths=stems),
        ):
            with patch.object(
                separator,
                "transcribe",
                return_value=TranscriptionResult(
                    success=True, segments=fake_segments, language="en"
                ),
            ):
                with patch(
                    "pikaraoke.lib.vocal_separator._search_online_lyrics",
                    return_value=None,
                ):
                    with patch(
                        "pikaraoke.lib.pitch_extractor.extract_pitch",
                        return_value=None,
                    ):
                        result = separator.process(song, title="Song")

        assert result.used_stems is True


class TestProcessAtomicAssWrite:
    """Fix 4: ASS write must be atomic (temp file in same dir + os.replace)."""

    @patch("pikaraoke.lib.vocal_separator.DEMUCS_AVAILABLE", False)
    @patch("pikaraoke.lib.vocal_separator.WHISPER_AVAILABLE", True)
    def test_no_temp_leftovers_on_success(self, separator, tmp_path):
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
        with patch.object(
            separator,
            "transcribe",
            return_value=TranscriptionResult(success=True, segments=fake_segments, language="en"),
        ):
            with patch("pikaraoke.lib.vocal_separator._search_online_lyrics", return_value=None):
                with patch(
                    "pikaraoke.lib.pitch_extractor.extract_pitch",
                    side_effect=ImportError("nope"),
                ):
                    result = separator.process(song, title="Song")

        assert os.path.exists(result.ass_path)
        # Only the final ASS exists; no stray temp file in the directory.
        leftovers = [
            p
            for p in os.listdir(tmp_path)
            if p.endswith(".ass") and p != os.path.basename(result.ass_path)
        ]
        assert leftovers == []
        assert os.path.getsize(result.ass_path) > 0


class TestProcessResumable:
    """Fix 5: a valid existing ASS is reused unless force=True."""

    @patch("pikaraoke.lib.vocal_separator.DEMUCS_AVAILABLE", False)
    @patch("pikaraoke.lib.vocal_separator.WHISPER_AVAILABLE", True)
    def test_skips_transcription_when_ass_exists(self, separator, tmp_path):
        song = str(tmp_path / "Song.mp4")
        open(song, "w").close()
        ass_path = _ass_path_for(song)
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write("[Events]\nDialogue: existing")

        with patch.object(separator, "transcribe") as mock_transcribe:
            result = separator.process(song, title="Song")

        mock_transcribe.assert_not_called()
        assert result.success is True
        assert result.ass_path == ass_path
        # Existing content is preserved.
        with open(ass_path, encoding="utf-8") as f:
            assert "existing" in f.read()

    @patch("pikaraoke.lib.vocal_separator.DEMUCS_AVAILABLE", False)
    @patch("pikaraoke.lib.vocal_separator.WHISPER_AVAILABLE", True)
    def test_force_reruns_even_when_ass_exists(self, separator, tmp_path):
        song = str(tmp_path / "Song.mp4")
        open(song, "w").close()
        ass_path = _ass_path_for(song)
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write("[Events]\nDialogue: stale")

        fake_segments = [
            {
                "start": 0,
                "end": 3,
                "text": "Hello",
                "words": [{"word": "Hello", "start": 0, "end": 3}],
                "no_speech_prob": 0.0,
            }
        ]
        with patch.object(
            separator,
            "transcribe",
            return_value=TranscriptionResult(success=True, segments=fake_segments, language="en"),
        ) as mock_transcribe:
            with patch("pikaraoke.lib.vocal_separator._search_online_lyrics", return_value=None):
                with patch(
                    "pikaraoke.lib.pitch_extractor.extract_pitch",
                    side_effect=ImportError("nope"),
                ):
                    result = separator.process(song, title="Song", force=True)

        mock_transcribe.assert_called_once()
        assert result.success is True
        with open(ass_path, encoding="utf-8") as f:
            assert "stale" not in f.read()

    @patch("pikaraoke.lib.vocal_separator.DEMUCS_AVAILABLE", False)
    @patch("pikaraoke.lib.vocal_separator.WHISPER_AVAILABLE", True)
    def test_empty_ass_does_not_short_circuit(self, separator, tmp_path):
        song = str(tmp_path / "Song.mp4")
        open(song, "w").close()
        open(_ass_path_for(song), "w").close()  # 0-byte stale ASS

        fake_segments = [
            {
                "start": 0,
                "end": 3,
                "text": "Hello",
                "words": [{"word": "Hello", "start": 0, "end": 3}],
                "no_speech_prob": 0.0,
            }
        ]
        with patch.object(
            separator,
            "transcribe",
            return_value=TranscriptionResult(success=True, segments=fake_segments, language="en"),
        ) as mock_transcribe:
            with patch("pikaraoke.lib.vocal_separator._search_online_lyrics", return_value=None):
                with patch(
                    "pikaraoke.lib.pitch_extractor.extract_pitch",
                    side_effect=ImportError("nope"),
                ):
                    separator.process(song, title="Song")

        mock_transcribe.assert_called_once()


class TestTranscribeTempCleanup:
    """Fix 6: the temp JSON must be unlinked even on subprocess failure."""

    @patch("pikaraoke.lib.vocal_separator.WHISPER_AVAILABLE", True)
    def test_temp_json_removed_on_failure(self, separator, tmp_path):
        song = str(tmp_path / "Song.mp4")
        open(song, "w").close()

        created: list[str] = []
        real_named = __import__("tempfile").NamedTemporaryFile

        def tracking_named(*args, **kwargs):
            f = real_named(*args, **kwargs)
            created.append(f.name)
            return f

        failed = MagicMock(returncode=1, stderr="whisper exploded", stdout="")
        with patch("pikaraoke.lib.vocal_separator.subprocess.run", return_value=failed):
            with patch("tempfile.NamedTemporaryFile", side_effect=tracking_named):
                with patch("tempfile.mktemp", side_effect=AssertionError("mktemp used")):
                    result = separator.transcribe(song)

        assert result.success is False
        assert created, "expected a NamedTemporaryFile to be created"
        for name in created:
            assert not os.path.exists(name), f"temp file leaked: {name}"


class _SyncThread:
    """Runs the thread target synchronously on start() for deterministic tests."""

    def __init__(self, target=None, args=(), **_kw):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


class TestEnsureSubtitlesAsync:
    def test_noop_and_warns_once_when_ai_unavailable(self, separator, events):
        notes = []
        events.on("notification", lambda msg, *a: notes.append(msg))
        separator.is_available = lambda: False
        assert separator.ensure_subtitles_async("/songs/a.mp4") is False
        assert separator.ensure_subtitles_async("/songs/b.mp4") is False
        assert sum("未安裝" in n for n in notes) == 1  # one-time hint, not per-song spam

    def test_noop_when_ass_already_exists(self, separator):
        separator.is_available = lambda: True
        separator.has_karaoke_ass = lambda p: True
        separator.process = MagicMock()
        assert separator.ensure_subtitles_async("/songs/a.mp4") is False
        separator.process.assert_not_called()

    def test_starts_background_process_when_missing(self, separator, monkeypatch):
        monkeypatch.setattr("pikaraoke.lib.vocal_separator.threading.Thread", _SyncThread)
        separator.is_available = lambda: True
        separator.has_karaoke_ass = lambda p: False
        separator.process = MagicMock()
        assert separator.ensure_subtitles_async("/songs/a.mp4") is True
        separator.process.assert_called_once_with("/songs/a.mp4")
        assert "/songs/a.mp4" not in separator._pending  # cleared after worker finishes

    def test_dedups_a_song_already_in_flight(self, separator):
        separator.is_available = lambda: True
        separator.has_karaoke_ass = lambda p: False
        separator.process = MagicMock()
        separator._pending.add("/songs/a.mp4")  # simulate an in-flight job
        assert separator.ensure_subtitles_async("/songs/a.mp4") is False
        separator.process.assert_not_called()

    def test_worker_survives_process_exception(self, separator, monkeypatch):
        monkeypatch.setattr("pikaraoke.lib.vocal_separator.threading.Thread", _SyncThread)
        separator.is_available = lambda: True
        separator.has_karaoke_ass = lambda p: False
        separator.process = MagicMock(side_effect=RuntimeError("boom"))
        # must not raise, and pending must be cleared in finally
        assert separator.ensure_subtitles_async("/songs/a.mp4") is True
        assert "/songs/a.mp4" not in separator._pending


class TestLanguageOverride:
    """P0-3: the /reprocess language override must actually reach Whisper (it was
    silently clobbered by a leftover ``language = ""`` accumulator), AND it must be
    neutralized before being interpolated into the ``python -c`` transcription script,
    or making the override work would open a subprocess code-injection hole."""

    def test_process_forwards_explicit_language_to_transcribe(self, separator, monkeypatch):
        # Regression: process() reset ``language = ""`` at the top, discarding the
        # explicit override before transcribe() ever saw it.
        monkeypatch.setattr("pikaraoke.lib.vocal_separator.DEMUCS_AVAILABLE", False)
        monkeypatch.setattr("pikaraoke.lib.vocal_separator.WHISPER_AVAILABLE", True)
        seen = {}

        def fake_transcribe(song_path, language=None):
            seen["language"] = language
            return TranscriptionResult(success=False, error="stop here")

        separator.transcribe = fake_transcribe
        separator.process("/songs/x.mp4", force=True, language="en")
        assert seen["language"] == "en"

    def test_sanitize_language_allows_two_letter_iso_codes(self):
        from pikaraoke.lib.vocal_separator import _sanitize_language

        assert _sanitize_language("en") == "en"
        assert _sanitize_language("zh") == "zh"
        assert _sanitize_language("ja") == "ja"

    def test_sanitize_language_rejects_injection_and_junk(self):
        from pikaraoke.lib.vocal_separator import _sanitize_language

        assert _sanitize_language("en'; import os; os.system('x') #") is None
        assert _sanitize_language("english") is None  # not two letters
        assert _sanitize_language("EN") is None  # not lowercase
        assert _sanitize_language("e n") is None
        assert _sanitize_language("") is None
        assert _sanitize_language(None) is None

    def test_transcribe_never_interpolates_raw_language_into_subprocess_script(
        self, separator, monkeypatch, tmp_path
    ):
        monkeypatch.setattr("pikaraoke.lib.vocal_separator.WHISPER_AVAILABLE", True)
        captured = {}

        def fake_run(cmd, *args, **kwargs):
            captured["script"] = cmd[2]  # [python, "-c", script, audio, out]
            return MagicMock(returncode=1, stderr="stopped")

        monkeypatch.setattr("pikaraoke.lib.vocal_separator.subprocess.run", fake_run)
        song = str(tmp_path / "song.mp4")
        open(song, "w").close()
        separator.transcribe(song, language="en'); import os; os.system('pwned') #")
        assert "os.system('pwned')" not in captured["script"]
        assert "import os; os.system" not in captured["script"]
