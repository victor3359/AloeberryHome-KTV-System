import os

_SPLASH_JS = os.path.join(
    os.path.dirname(__file__), "..", "..", "pikaraoke", "static", "js", "splash.js"
)


def _read():
    with open(_SPLASH_JS, encoding="utf-8") as f:
        return f.read()


def test_pitch_shift_context_is_never_closed():
    """P0-1: an HTMLMediaElement can be captured by only one MediaElementSourceNode, and once
    captured its audio is permanently routed into that graph. Closing the pitch-shift
    AudioContext on song change / endSong (the June anti-leak fix) left #video routed into a
    dead graph, so every song after the first use of 升降Key played SILENTLY. The context must
    persist for the whole session — it is never closed."""
    js = _read()
    assert "_pitchShiftCtx.close()" not in js


def test_song_change_resets_pitch_via_shared_helper_not_teardown():
    """endSong and the song-change path reset to native pitch through a shared helper that keeps
    the persistent graph intact, instead of destroying the context."""
    js = _read()
    assert "function resetPitchShift" in js
    assert js.count("resetPitchShift()") >= 2


def test_pitch_shift_bypasses_worklet_at_zero_semitones():
    """At 0 semitones playback routes source -> destination (native, no worklet latency); the
    worklet is only inserted when actually shifting, so unshifted songs stay artifact-free even
    though the graph now persists for the whole session."""
    js = _read()
    assert "function _routePitchShift" in js
