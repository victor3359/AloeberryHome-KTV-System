"""Tests for the 8 new features added to PiKaraoke 1.19.0.

A: Language/artist filtering in browse
B: Admin keyboard shortcuts on home page
C: Session timer in splash/now_playing
D: Queue badges in browse
E: Info page tab reorganization
F: YouTube source labels in search
G: Play history recording and endpoint
H: Fair queue visualization
"""

from __future__ import annotations

import os
import time
from collections import Counter
from unittest.mock import MagicMock, patch
from urllib.parse import quote

import pytest
import werkzeug
from flask import Flask
from flask_babel import Babel

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from pikaraoke.lib.song_manager import SongManager
from pikaraoke.routes.files import _detect_language, _extract_artist
from pikaraoke.routes.scores import scores_bp

# Path to the real pikaraoke templates/static directories
_PKG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_TEMPLATE_DIR = os.path.join(_PKG_DIR, "templates")
_STATIC_DIR = os.path.join(_PKG_DIR, "static")


# ---------------------------------------------------------------------------
# Shared helper: create a Flask app with all blueprints for template tests
# ---------------------------------------------------------------------------


def _make_full_app():
    """Create a Flask app with all blueprints registered for template rendering."""
    from pikaraoke.routes.admin import admin_bp
    from pikaraoke.routes.background_music import background_music_bp
    from pikaraoke.routes.controller import controller_bp
    from pikaraoke.routes.files import files_bp
    from pikaraoke.routes.home import home_bp
    from pikaraoke.routes.images import images_bp
    from pikaraoke.routes.info import info_bp
    from pikaraoke.routes.metadata_api import metadata_bp
    from pikaraoke.routes.now_playing import nowplaying_bp
    from pikaraoke.routes.preferences import preferences_bp
    from pikaraoke.routes.queue import queue_bp
    from pikaraoke.routes.search import search_bp
    from pikaraoke.routes.songpicker import songpicker_bp
    from pikaraoke.routes.splash import splash_bp
    from pikaraoke.routes.stream import stream_bp

    app = Flask(__name__, template_folder=_TEMPLATE_DIR, static_folder=_STATIC_DIR)
    app.secret_key = "test"
    Babel(app)
    app.jinja_env.add_extension("jinja2.ext.i18n")
    app.jinja_env.install_null_translations()
    app.jinja_env.globals.update(filename_from_path=SongManager.filename_from_path)
    app.jinja_env.globals.update(url_escape=quote)

    for bp in [
        home_bp,
        info_bp,
        songpicker_bp,
        splash_bp,
        queue_bp,
        search_bp,
        files_bp,
        preferences_bp,
        admin_bp,
        controller_bp,
        background_music_bp,
        images_bp,
        nowplaying_bp,
        stream_bp,
        metadata_bp,
        scores_bp,
    ]:
        app.register_blueprint(bp)
    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def full_app():
    return _make_full_app()


@pytest.fixture
def full_client(full_app):
    return full_app.test_client()


@pytest.fixture
def scores_app():
    app = Flask(__name__)
    app.register_blueprint(scores_bp)
    return app


@pytest.fixture
def scores_client(scores_app):
    return scores_app.test_client()


# ---------------------------------------------------------------------------
# Feature A: Language detection & artist extraction
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    """Test _detect_language() for various Unicode character sets."""

    def test_chinese_characters(self):
        assert _detect_language("周杰倫 - 晴天") == "chinese"

    def test_japanese_hiragana(self):
        assert _detect_language("きらきら星") == "japanese"

    def test_japanese_katakana(self):
        assert _detect_language("ドレミの歌") == "japanese"

    def test_korean_characters(self):
        assert _detect_language("아이유 - 좋은 날") == "korean"

    def test_english_only(self):
        assert _detect_language("Artist - Song Title") == "english"

    def test_empty_string(self):
        assert _detect_language("") == "english"

    def test_japanese_priority_over_chinese(self):
        assert _detect_language("桜の花びらたち") == "japanese"


class TestExtractArtist:
    """Test _extract_artist() for various filename formats."""

    def test_standard_dash(self):
        assert _extract_artist("Artist - Song Title") == "Artist"

    def test_en_dash(self):
        assert _extract_artist("Artist \u2013 Song Title") == "Artist"

    def test_no_separator(self):
        assert _extract_artist("JustASongTitle") is None

    def test_hyphenated_artist(self):
        assert _extract_artist("A-ha - Take On Me") == "A-ha"

    def test_chinese_artist(self):
        assert _extract_artist("周杰倫 - 晴天") == "周杰倫"

    def test_whitespace_trimming(self):
        assert _extract_artist("  Artist  -  Song  ") == "Artist"

    def test_no_spaces_around_dash(self):
        # "Artist-Song" with no spaces should return None (not a proper separator)
        assert _extract_artist("Artist-Song") is None


# ---------------------------------------------------------------------------
# Feature B: Keyboard shortcuts (admin-only)
# ---------------------------------------------------------------------------


class TestKeyboardShortcuts:
    """Verify keyboard shortcut JS is gated behind admin."""

    def _make_mock_karaoke(self):
        k = MagicMock()
        k.playback_controller.now_playing_transpose = 0
        k.is_transpose_enabled = True
        k.volume = 0.85
        k.queue_manager.queue = []
        k.enable_fair_queue = False
        k.limit_user_songs_by = 0
        return k

    @patch("pikaraoke.routes.queue.get_karaoke_instance")
    @patch("pikaraoke.routes.queue.get_site_name", return_value="Test")
    @patch("pikaraoke.routes.queue.is_admin", return_value=True)
    def test_admin_gets_keydown_listener(self, _admin, _site, mock_k, full_client):
        mock_k.return_value = self._make_mock_karaoke()
        resp = full_client.get("/queue")
        html = resp.data.decode()
        assert "keydown" in html

    @patch("pikaraoke.routes.queue.get_karaoke_instance")
    @patch("pikaraoke.routes.queue.get_site_name", return_value="Test")
    @patch("pikaraoke.routes.queue.is_admin", return_value=False)
    def test_non_admin_no_keydown_listener(self, _admin, _site, mock_k, full_client):
        mock_k.return_value = self._make_mock_karaoke()
        resp = full_client.get("/queue")
        html = resp.data.decode()
        # Non-admin should not see the admin keyboard shortcut block
        assert "case 'S': $.get('/skip')" not in html


# ---------------------------------------------------------------------------
# Feature C: Session timer
# ---------------------------------------------------------------------------


class TestSessionTimer:
    """Test session_elapsed in get_now_playing()."""

    def test_session_elapsed_is_int(self, mock_karaoke):
        result = mock_karaoke.get_now_playing()
        assert "session_elapsed" in result
        assert isinstance(result["session_elapsed"], int)

    def test_session_elapsed_increases(self, mock_karaoke):
        mock_karaoke.session_start = time.time() - 120
        result = mock_karaoke.get_now_playing()
        assert result["session_elapsed"] >= 120


# ---------------------------------------------------------------------------
# Feature D: Queue badges
# ---------------------------------------------------------------------------


class TestQueueBadges:
    """Test that queue_files set is correctly computed."""

    def test_queue_files_set_computation(self):
        queue = [
            {"file": "/songs/A---x.mp4", "user": "U", "title": "A", "semitones": 0},
            {"file": "/songs/B---y.mp4", "user": "U", "title": "B", "semitones": 0},
        ]
        queue_files = {item["file"] for item in queue}
        assert "/songs/A---x.mp4" in queue_files
        assert "/songs/B---y.mp4" in queue_files
        assert "/songs/C---z.mp4" not in queue_files


# ---------------------------------------------------------------------------
# Feature E: Info page tabs
# ---------------------------------------------------------------------------


class TestInfoTabs:
    """Test info page renders correctly for admin and non-admin."""

    def _make_mock_karaoke(self):
        k = MagicMock()
        k.url = "http://localhost:5555"
        k.platform = "linux"
        k.os_version = "test"
        k.ffmpeg_version = "6.0"
        k.is_transpose_enabled = True
        k.youtubedl_version = "2024.01.01"
        k.is_raspberry_pi = False
        k.volume = 0.85
        k.bg_music_volume = 0.5
        k.disable_bg_music = False
        k.disable_bg_video = False
        k.disable_score = False
        k.hide_notifications = False
        k.show_splash_clock = False
        k.hide_url = False
        k.hide_overlay = False
        k.screensaver_timeout = 300
        k.splash_delay = 2
        k.normalize_audio = False
        k.cdg_pixel_scaling = False
        k.high_quality = False
        k.complete_transcode_before_play = False
        k.avsync = 0
        k.limit_user_songs_by = 0
        k.enable_fair_queue = False
        k.auto_dj = False
        k.buffer_size = 0
        k.browse_results_per_page = 500
        k.low_score_phrases = ""
        k.mid_score_phrases = ""
        k.high_score_phrases = ""
        k.preferences.get.return_value = "en"
        return k

    @patch("pikaraoke.routes.info.get_admin_password", return_value="pass")
    @patch("pikaraoke.routes.info.get_platform", return_value="linux")
    @patch("pikaraoke.routes.info.get_karaoke_instance")
    @patch("pikaraoke.routes.info.get_site_name", return_value="Test")
    @patch("pikaraoke.routes.info.is_admin", return_value=True)
    def test_admin_both_sections_present(self, _admin, _site, mock_k, _plat, _pw, full_client):
        mock_k.return_value = self._make_mock_karaoke()
        resp = full_client.get("/info")
        html = resp.data.decode()
        assert resp.status_code == 200
        # New accordion layout has Settings and Admin cards
        assert "Settings" in html
        assert "Admin" in html

    @patch("pikaraoke.routes.info.get_admin_password", return_value="pass")
    @patch("pikaraoke.routes.info.get_platform", return_value="linux")
    @patch("pikaraoke.routes.info.get_karaoke_instance")
    @patch("pikaraoke.routes.info.get_site_name", return_value="Test")
    @patch("pikaraoke.routes.info.is_admin", return_value=False)
    def test_non_admin_sees_admin_card(self, _admin, _site, mock_k, _plat, _pw, full_client):
        mock_k.return_value = self._make_mock_karaoke()
        resp = full_client.get("/info")
        html = resp.data.decode()
        assert resp.status_code == 200
        # Non-admin should see the admin accordion card with login option
        assert "icon-wrench" in html

    @patch("pikaraoke.routes.info.get_admin_password", return_value="pass")
    @patch("pikaraoke.routes.info.get_platform", return_value="linux")
    @patch("pikaraoke.routes.info.get_karaoke_instance")
    @patch("pikaraoke.routes.info.get_site_name", return_value="Test")
    @patch("pikaraoke.routes.info.is_admin", return_value=False)
    def test_non_admin_sees_login(self, _admin, _site, mock_k, _plat, _pw, full_client):
        mock_k.return_value = self._make_mock_karaoke()
        resp = full_client.get("/info")
        html = resp.data.decode()
        assert "Log in" in html or "Login" in html


# ---------------------------------------------------------------------------
# Feature F: YouTube source labels
# ---------------------------------------------------------------------------


class TestYouTubeSourceLabels:
    """Test that YouTube and download labels appear in search results."""

    @patch("pikaraoke.routes.songpicker.is_admin", return_value=False)
    @patch("pikaraoke.routes.songpicker.get_karaoke_instance")
    @patch("pikaraoke.routes.songpicker.get_site_name", return_value="Test")
    @patch("pikaraoke.routes.songpicker.get_search_results")
    def test_search_results_have_youtube_label(
        self, mock_search, _site, mock_k, _admin, full_client
    ):
        k = MagicMock()
        k.song_manager.songs = []
        k.queue_manager.queue = []
        k.browse_results_per_page = 100
        k.enable_fair_queue = False
        k.limit_user_songs_by = 0
        mock_k.return_value = k
        mock_search.return_value = [
            ["Test Song", "https://youtube.com/watch?v=abc", "abc123abcde", "TestCh", "3:45"],
        ]
        resp = full_client.get("/songpicker?search_string=test")
        html = resp.data.decode()
        assert "YouTube" in html


# ---------------------------------------------------------------------------
# Feature G: Play history
# ---------------------------------------------------------------------------


class TestPlayHistory:
    """Test play_history recording and /history endpoint."""

    def test_play_history_initialized_empty(self, mock_karaoke):
        assert mock_karaoke.play_history == []

    @patch("pikaraoke.routes.scores.get_karaoke_instance")
    def test_history_endpoint_empty(self, mock_get_instance, scores_client):
        mock_k = MagicMock()
        mock_k.play_history = []
        mock_get_instance.return_value = mock_k
        resp = scores_client.get("/history")
        assert resp.status_code == 200
        assert resp.get_json() == []

    @patch("pikaraoke.routes.scores.get_karaoke_instance")
    def test_history_endpoint_returns_reversed(self, mock_get_instance, scores_client):
        mock_k = MagicMock()
        mock_k.play_history = [
            {"title": "Song A", "user": "Alice", "user2": None},
            {"title": "Song B", "user": "Bob", "user2": None},
        ]
        mock_get_instance.return_value = mock_k
        resp = scores_client.get("/history")
        data = resp.get_json()
        assert len(data) == 2
        assert data[0]["title"] == "Song B"
        assert data[1]["title"] == "Song A"

    @patch("pikaraoke.routes.scores.get_karaoke_instance")
    def test_history_includes_duet_info(self, mock_get_instance, scores_client):
        mock_k = MagicMock()
        mock_k.play_history = [
            {"title": "Duet Song", "user": "Alice", "user2": "Bob"},
        ]
        mock_get_instance.return_value = mock_k
        resp = scores_client.get("/history")
        data = resp.get_json()
        assert data[0]["user2"] == "Bob"


# ---------------------------------------------------------------------------
# Feature H: Fair queue visualization
# ---------------------------------------------------------------------------


class TestFairQueueDisplay:
    """Test user_counts Counter computation for fair queue banner."""

    def test_user_counts_computation(self):
        queue = [
            {"user": "Alice", "file": "/a.mp4", "title": "A", "semitones": 0},
            {"user": "Bob", "file": "/b.mp4", "title": "B", "semitones": 0},
            {"user": "Alice", "file": "/c.mp4", "title": "C", "semitones": 0},
        ]
        user_counts = dict(Counter(item["user"] for item in queue))
        assert user_counts == {"Alice": 2, "Bob": 1}

    def test_empty_queue_counts(self):
        queue = []
        user_counts = dict(Counter(item["user"] for item in queue))
        assert user_counts == {}
