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


def test_pitch_analyzer_band_limits_tau_for_efficiency():
    """P1.5-2: the YIN searched tau over the full [1, halfLen) (~2048 for fftSize 4096), i.e.
    ~4.2M ops/frame at 60fps on the TV main thread. Limit tau to the 80-1100 Hz vocal band."""
    js = _read(_PITCH_ANALYZER)
    assert "tauMin" in js and "tauMax" in js
    assert "/ 1100" in js and "/ 80" in js  # bounds derived from sampleRate/1100 and /80


def test_pitch_analyzer_guards_against_nan_pitch():
    """P1.5-3: parabolic interpolation divides by (s0 - 2s1 + s2); when that is 0 the pitch is
    NaN, and NaN<80||NaN>1100 is false, so NaN leaked to the meter (frozen 'NaN%', unfair miss)."""
    js = _read(_PITCH_ANALYZER)
    assert "Number.isFinite" in js  # final filter rejects a non-finite pitch
    assert "denom" in js  # parabolic denominator guarded before dividing


def test_pitch_analyzer_throttles_and_skips_when_inactive():
    """P1.5-2: detection ran on every requestAnimationFrame. Throttle it and skip when inactive
    (video paused), so the O(window*tau) YIN is not run 60x/second continuously."""
    js = _read(_PITCH_ANALYZER)
    assert "shouldAnalyze" in js
    assert "performance.now()" in js


def test_mic_scoring_resets_meter_at_song_start_to_prevent_score_carryover():
    """P1-2: window._pitchMeter is only replaced when a song's mic init SUCCEEDS. If the next
    song's getUserMedia fails, the previous song's accumulated frames survive and endSong records
    that score for the new singer (leaderboard corruption). _initMicScoring must reset the meter
    at the top, before the mic-init try-block, so a failed init leaves 0 frames not a stale score.
    """
    js = _read(_SPLASH_JS)
    init_idx = js.index("async function _initMicScoring")
    try_idx = js.index("try {", init_idx)
    head = js[init_idx:try_idx]
    assert "_pitchMeter.reset()" in head, "must reset the meter before the mic-init try-block"
