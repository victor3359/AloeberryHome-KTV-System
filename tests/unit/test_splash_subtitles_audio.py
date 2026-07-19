import os
import re

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_SPLASH_JS = os.path.join(_PKG, "static", "js", "splash.js")
_SUBS = os.path.join(_PKG, "static", "js", "modules", "subtitles.js")
_AUDIO = os.path.join(_PKG, "static", "js", "modules", "audio-pipeline.js")
_PLAYER_CORE = os.path.join(_PKG, "static", "js", "modules", "player-core.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_subtitles_module_owns_octopus():
    """Slice 7: the SubtitlesOctopus block moves out of handleNowPlayingUpdate into
    modules/subtitles.js, which owns the octopus instance + last URL."""
    m = _read(_SUBS)
    assert re.search(r"^export function updateSubtitles\b", m, re.M)
    assert "new SubtitlesOctopus" in m
    # the call site lives in player-core (slice 9); no octopus construction in splash/player-core.
    pc = _read(_PLAYER_CORE)
    assert "updateSubtitles(np, video, d.getUiScale())" in pc
    assert "new SubtitlesOctopus" not in pc
    assert "new SubtitlesOctopus" not in _read(_SPLASH_JS)


def test_audio_pipeline_module_owns_hls():
    """Slice 7: the HLS.js block + audio_mode_switch move into modules/audio-pipeline.js, which
    owns the Hls instance + track map shared by the player-core and the switch handler."""
    m = _read(_AUDIO)
    for name in ("setupHls", "destroyHls", "switchAudioTrack"):
        assert re.search(rf"^export function {name}\b", m, re.M), name
    assert "new Hls(" in m
    # the call sites live in player-core (slice 9); no Hls construction in splash/player-core.
    pc = _read(_PLAYER_CORE)
    assert "setupHls(streamUrl, video, d.browser)" in pc
    assert "switchAudioTrack(mode, d.getVideoPlayer())" in pc
    assert "new Hls(" not in pc
    assert "new Hls(" not in _read(_SPLASH_JS)
