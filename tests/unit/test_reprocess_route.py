"""Tests for the /reprocess route — ensures reprocessing always regenerates.

The route deletes companion files then re-runs the AI pipeline. It must call
VocalSeparator.process(force=True) so a stale ASS never short-circuits the
regeneration (see vocal_separator resumable-transcription fix).
"""

import os
from unittest.mock import MagicMock, patch

import pytest
import werkzeug
from flask import Flask

# Monkeypatch werkzeug.__version__ for Flask compatibility if missing
if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from pikaraoke.routes.scores import scores_bp


@pytest.fixture
def app():
    test_app = Flask(__name__)
    test_app.register_blueprint(scores_bp)
    return test_app


@pytest.fixture
def client(app):
    return app.test_client()


class TestReprocessRoute:
    @patch("pikaraoke.routes.scores.get_karaoke_instance")
    def test_reprocess_calls_process_with_force(self, mock_get_instance, client):
        """The background reprocess must pass force=True so it regenerates."""
        mock_karaoke = MagicMock()
        mock_karaoke.song_manager.filename_from_path.return_value = "My Song"
        mock_get_instance.return_value = mock_karaoke

        # Run the spawned thread's target synchronously for a deterministic assert.
        def run_target(target=None, daemon=None, **kwargs):
            thread = MagicMock()
            thread.start.side_effect = lambda: target()
            return thread

        with patch("threading.Thread", side_effect=run_target):
            response = client.post("/reprocess", json={"song": "/songs/My Song.mp4"})

        assert response.status_code == 200
        mock_karaoke.vocal_separator.process.assert_called_once()
        _, kwargs = mock_karaoke.vocal_separator.process.call_args
        assert kwargs.get("force") is True

    @patch("pikaraoke.routes.scores.get_karaoke_instance")
    def test_reprocess_forwards_language_override(self, mock_get_instance, client):
        """An explicit language (e.g. for a non-CJK song Whisper mis-detects) is forwarded."""
        mock_karaoke = MagicMock()
        mock_karaoke.song_manager.filename_from_path.return_value = "My Song"
        mock_get_instance.return_value = mock_karaoke

        def run_target(target=None, daemon=None, **kwargs):
            thread = MagicMock()
            thread.start.side_effect = lambda: target()
            return thread

        with patch("threading.Thread", side_effect=run_target):
            client.post("/reprocess", json={"song": "/songs/My Song.mp4", "language": "en"})

        _, kwargs = mock_karaoke.vocal_separator.process.call_args
        assert kwargs.get("language") == "en"

    @patch("pikaraoke.routes.scores.get_karaoke_instance")
    def test_reprocess_language_defaults_none(self, mock_get_instance, client):
        mock_karaoke = MagicMock()
        mock_karaoke.song_manager.filename_from_path.return_value = "My Song"
        mock_get_instance.return_value = mock_karaoke

        def run_target(target=None, daemon=None, **kwargs):
            thread = MagicMock()
            thread.start.side_effect = lambda: target()
            return thread

        with patch("threading.Thread", side_effect=run_target):
            client.post("/reprocess", json={"song": "/songs/My Song.mp4"})

        _, kwargs = mock_karaoke.vocal_separator.process.call_args
        assert kwargs.get("language") is None

    @patch("pikaraoke.routes.scores.get_karaoke_instance")
    def test_reprocess_requires_song(self, mock_get_instance, client):
        mock_get_instance.return_value = MagicMock()
        response = client.post("/reprocess", json={})
        assert response.status_code == 400

    @patch("pikaraoke.routes.scores.get_karaoke_instance")
    def test_reprocess_deletes_pitch_json(self, mock_get_instance, client, tmp_path):
        """P1-7: reprocess must delete _pitch.json too. extract_pitch skips when the output
        already exists, so leaving the old pitch curve makes mic scoring grade singers against
        the stale (often wrong-song / bad-separation) reference forever."""
        mock_karaoke = MagicMock()
        mock_karaoke.song_manager.filename_from_path.return_value = "My Song"
        mock_get_instance.return_value = mock_karaoke
        song = str(tmp_path / "My Song.mp4")
        base = str(tmp_path / "My Song")
        companions = [
            base + s for s in ("_vocals.mp3", "_instrumental.mp3", "_karaoke.ass", "_pitch.json")
        ]
        for c in companions:
            with open(c, "w") as f:
                f.write("x")

        # Deletion happens synchronously in the route before the thread; keep process() from running.
        def run_target(target=None, daemon=None, **kwargs):
            thread = MagicMock()
            thread.start.side_effect = lambda: None
            return thread

        with patch("threading.Thread", side_effect=run_target):
            response = client.post("/reprocess", json={"song": song})

        assert response.status_code == 200
        for c in companions:
            assert not os.path.exists(c), f"reprocess left a stale companion: {c}"
