"""Unit tests for pitch_extractor module."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from pikaraoke.lib.pitch_extractor import extract_pitch


class TestExtractPitchSkipsExisting:
    """Tests for early return when pitch file already exists."""

    def test_skips_if_pitch_file_exists(self, tmp_path):
        """Return existing path immediately without launching subprocess."""
        vocal = tmp_path / "song_vocals.mp3"
        vocal.write_bytes(b"fake")
        pitch = tmp_path / "song_pitch.json"
        pitch.write_text("[]")

        with patch("pikaraoke.lib.pitch_extractor.subprocess") as mock_sub:
            result = extract_pitch(str(vocal), str(pitch))

        assert result == str(pitch)
        mock_sub.run.assert_not_called()

    def test_skips_if_companion_pitch_exists(self, tmp_path):
        """Return early when default companion _pitch.json already exists."""
        vocal = tmp_path / "song_vocals.mp3"
        vocal.write_bytes(b"fake")
        pitch = tmp_path / "song_pitch.json"
        pitch.write_text("[]")

        with patch("pikaraoke.lib.pitch_extractor.subprocess") as mock_sub:
            result = extract_pitch(str(vocal))

        assert result == str(pitch)
        mock_sub.run.assert_not_called()


class TestExtractPitchNoVocals:
    """Tests for missing vocal file."""

    def test_returns_none_if_no_vocals(self, tmp_path):
        """Return None immediately when the audio file does not exist."""
        missing = tmp_path / "nonexistent_vocals.mp3"

        result = extract_pitch(str(missing))

        assert result is None


class TestExtractPitchOutputPath:
    """Tests for default output path derivation."""

    def test_output_path_defaults_to_companion(self, tmp_path):
        """Default output strips _vocals suffix and appends _pitch.json."""
        vocal = tmp_path / "My Song---abc12345678_vocals.mp3"
        vocal.write_bytes(b"fake")

        mock_result = MagicMock()
        mock_result.returncode = 0

        expected = str(tmp_path / "My Song---abc12345678_pitch.json")

        with patch("pikaraoke.lib.pitch_extractor.subprocess.run", return_value=mock_result):
            with patch("pikaraoke.lib.pitch_extractor.os.path.exists") as mock_exists:
                # audio_path exists, output_path does NOT exist yet, then
                # after subprocess it DOES exist
                mock_exists.side_effect = lambda p: p == str(vocal) or (
                    p == expected and mock_result.returncode == 0
                )
                result = extract_pitch(str(vocal))

        assert result == expected

    def test_output_path_without_vocals_suffix(self, tmp_path):
        """When audio path has no _vocals suffix, append _pitch.json directly."""
        audio = tmp_path / "plain_audio.mp3"
        audio.write_bytes(b"fake")

        mock_result = MagicMock()
        mock_result.returncode = 0

        expected = str(tmp_path / "plain_audio_pitch.json")

        with patch("pikaraoke.lib.pitch_extractor.subprocess.run", return_value=mock_result):
            with patch("pikaraoke.lib.pitch_extractor.os.path.exists") as mock_exists:
                mock_exists.side_effect = lambda p: p == str(audio) or (
                    p == expected and mock_result.returncode == 0
                )
                result = extract_pitch(str(audio))

        assert result == expected


class TestExtractPitchSubprocess:
    """Tests for subprocess invocation."""

    def test_subprocess_called_with_correct_args(self, tmp_path):
        """Verify subprocess.run receives the expected command and kwargs."""
        vocal = tmp_path / "song_vocals.mp3"
        vocal.write_bytes(b"fake")
        output = tmp_path / "song_pitch.json"

        mock_result = MagicMock()
        mock_result.returncode = 0

        # Track calls to os.path.exists: audio_path -> True, output_path (pre-check) -> False,
        # output_path (post-subprocess) -> True
        exists_calls = []

        def fake_exists(p):
            exists_calls.append(p)
            if p == str(vocal):
                return True
            if p == str(output):
                # First check (skip existing?) returns False, second (post-run?) returns True
                return len([c for c in exists_calls if c == str(output)]) > 1
            return False

        with patch("pikaraoke.lib.pitch_extractor.subprocess.run", return_value=mock_result) as mock_run:
            with patch("pikaraoke.lib.pitch_extractor.os.path.exists", side_effect=fake_exists):
                extract_pitch(str(vocal), str(output), hop_size=0.1)

        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        cmd = args[0]

        # First arg is the Python executable
        assert "python" in cmd[0].lower() or cmd[0].endswith("python.exe") or cmd[0].endswith("python3")
        # -c flag for inline script
        assert cmd[1] == "-c"
        # Script is a string (cmd[2])
        assert isinstance(cmd[2], str)
        # audio_path, output_path, hop_size
        assert cmd[3] == str(vocal)
        assert cmd[4] == str(output)
        assert cmd[5] == "0.1"
        # Key kwargs
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["timeout"] == 300

    def test_handles_subprocess_failure(self, tmp_path):
        """Return None when subprocess exits with non-zero code."""
        vocal = tmp_path / "song_vocals.mp3"
        vocal.write_bytes(b"fake")
        output = tmp_path / "song_pitch.json"

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "ffmpeg not found"

        with patch("pikaraoke.lib.pitch_extractor.subprocess.run", return_value=mock_result):
            result = extract_pitch(str(vocal), str(output))

        assert result is None

    def test_handles_subprocess_timeout(self, tmp_path):
        """Return None when subprocess times out."""
        vocal = tmp_path / "song_vocals.mp3"
        vocal.write_bytes(b"fake")
        output = tmp_path / "song_pitch.json"

        with patch(
            "pikaraoke.lib.pitch_extractor.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="test", timeout=300),
        ):
            result = extract_pitch(str(vocal), str(output))

        assert result is None

    def test_handles_unexpected_exception(self, tmp_path):
        """Return None on any unexpected error during subprocess execution."""
        vocal = tmp_path / "song_vocals.mp3"
        vocal.write_bytes(b"fake")
        output = tmp_path / "song_pitch.json"

        with patch(
            "pikaraoke.lib.pitch_extractor.subprocess.run",
            side_effect=OSError("permission denied"),
        ):
            result = extract_pitch(str(vocal), str(output))

        assert result is None
