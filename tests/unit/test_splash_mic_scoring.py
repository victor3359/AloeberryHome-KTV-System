import os

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_SPLASH_JS = os.path.join(_PKG, "static", "js", "splash.js")
_PITCH_ANALYZER = os.path.join(_PKG, "static", "js", "pitch-analyzer.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_pitch_analyzer_stop_releases_stream_and_context():
    """P1-1: stop() must stop the mic MediaStream tracks AND close the AudioContext, not only
    disconnect the source node. Otherwise every song leaks a live getUserMedia capture + an
    AudioContext; a 3-hour session stacks dozens, saturating the TV CPU and never releasing the
    OS mic indicator."""
    js = _read(_PITCH_ANALYZER)
    assert "this.stream = stream" in js, "constructor must keep the stream so stop() can release it"
    assert "getTracks()" in js, "stop() must stop the mic tracks"
    assert "audioContext.close()" in js, "stop() must close the AudioContext"


def test_splash_stops_mic_scoring_on_reinit_and_skip():
    """P1-1: _initMicScoring runs per song and the socket 'skip' handler pauses without calling
    endSong, so the previous analyzer's rAF YIN loop keeps spinning and its resources leak unless
    it is stopped in both places. A shared stopMicScoring() helper covers endSong, re-init, skip."""
    js = _read(_SPLASH_JS)
    assert "function stopMicScoring" in js
    # definition + at least the endSong, re-init, and skip call sites.
    assert js.count("stopMicScoring()") >= 3
