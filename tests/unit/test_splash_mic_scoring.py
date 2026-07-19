import os
import re

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_SPLASH_JS = os.path.join(_PKG, "static", "js", "splash.js")
_PITCH_ANALYZER = os.path.join(_PKG, "static", "js", "pitch-analyzer.js")
_PLAYER_CORE = os.path.join(_PKG, "static", "js", "modules", "player-core.js")
_MIC = os.path.join(_PKG, "static", "js", "modules", "mic-scoring.js")


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


def test_mic_scoring_module_exists_and_exports_api():
    """Slice 4.5: mic scoring becomes its own module owning the analyzer/meter/reference curve, so
    splash.js is a pure composition root. player-core drives it through a small API."""
    m = _read(_MIC)
    for name in (
        "export function initMicScoring(",
        "export function stopMicScoring(",
        "export async function startMicScoring(",
        "export function getMicScore(",
        "export function hideMeter(",
    ):
        assert name in m, f"mic-scoring.js must define `{name}`"
    # It imports the pitch primitives directly (they are ES modules) — no injection needed for them.
    assert re.search(
        r'import \{[^}]*\bPitchAnalyzer\b[^}]*\} from "/static/js/pitch-analyzer\.js"', m
    )
    assert re.search(r'import \{[^}]*\bPitchMeter\b[^}]*\} from "/static/js/pitch-meter\.js"', m)


def test_mic_scoring_encapsulates_state_as_module_private_not_window_globals():
    """The analyzer/meter/reference-pitch were window globals shared implicitly with player-core.
    They become module-private so the only cross-module contract is the exported API. A stray
    window._pitchMeter reader elsewhere would now silently see nothing — there must be none."""
    m = _read(_MIC)
    assert "let _analyzer" in m and "let _meter" in m and "let _referencePitch" in m
    for leaked in ("window._pitchMeter", "window._pitchAnalyzer", "window._referencePitch"):
        assert leaked not in m, f"mic-scoring.js must not use the {leaked} global"
    # #video is splash-owned; the module reads it only through the injected accessor.
    assert "d.getVideoPlayer()" in m
    # No circular import back into splash.
    assert re.search(r'from\s+["\'][^"\']*splash\.js["\']', m) is None


def test_mic_scoring_resets_meter_at_song_start_to_prevent_score_carryover():
    """P1-2: the meter is only replaced when a song's mic init SUCCEEDS. If the next song's
    getUserMedia fails, the previous song's accumulated frames survive and endSong records that
    score for the new singer (leaderboard corruption). startMicScoring must reset the meter at the
    top, before the mic-init try-block, so a failed init leaves 0 frames not a stale score."""
    m = _read(_MIC)
    init_idx = m.index("export async function startMicScoring")
    try_idx = m.index("try {", init_idx)
    head = m[init_idx:try_idx]
    assert "_meter.reset()" in head, "must reset the meter before the mic-init try-block"


def test_player_core_drives_mic_scoring_through_the_module_api():
    """P1-1: startMicScoring runs per song and the socket 'skip' handler pauses without calling
    endSong, so the previous analyzer's rAF YIN loop keeps spinning and leaks unless stopped in
    both endSong and skip. player-core imports the module API and no longer reaches window._pitchMeter
    nor the old d.stopMicScoring/d.initMicScoring injected seams."""
    pc = _read(_PLAYER_CORE)
    assert re.search(
        r'import \{[^}]*\bstopMicScoring\b[^}]*\} from "/static/js/modules/mic-scoring\.js"', pc
    )
    assert "startMicScoring(" in pc  # handleNowPlayingUpdate, per song
    assert pc.count("stopMicScoring()") >= 2  # endSong + skip
    assert pc.count("hideMeter()") >= 2  # endSong + skip (was `if (window._pitchMeter) .hide()`)
    assert "getMicScore()" in pc  # endSong reads the final score through the module
    assert "window._pitchMeter" not in pc
    assert "d.stopMicScoring" not in pc and "d.initMicScoring" not in pc


def test_player_core_drops_dead_isscoreshown_state():
    """Review cleanup #2: isScoreShown was set true/false in endSong but never read anywhere —
    dead state. It must be gone."""
    pc = _read(_PLAYER_CORE)
    assert "isScoreShown" not in pc


def test_player_core_takes_getsemitoneslabel_as_injected_dep_not_a_bare_global():
    """Review cleanup #3: getSemitonesLabel is defined in base.html; reading it as a bare global
    made player-core look self-contained while silently depending on the page. It is injected via
    the deps so the coupling is explicit (and only exercised on a transposed song)."""
    pc = _read(_PLAYER_CORE)
    assert "d.getSemitonesLabel(" in pc
    # not read as a bare/global call
    assert re.search(r"(?<![.\w])getSemitonesLabel\(", pc) is None


def test_splash_wires_mic_scoring_and_no_longer_defines_it():
    """splash.js becomes a pure composition root: it injects #video into the mic-scoring module and
    drops the analyzer/meter code + the pitch classes (which moved to mic-scoring)."""
    js = _read(_SPLASH_JS)
    assert 'from "/static/js/modules/mic-scoring.js"' in js and "initMicScoring({" in js
    assert "getVideoPlayer" in js  # injected accessor
    # moved out: the functions and the window pitch globals no longer live in splash.
    assert "function stopMicScoring" not in js
    assert "_initMicScoring" not in js
    assert "window._pitch" not in js
    # PitchAnalyzer/PitchMeter are imported by mic-scoring now, not splash.
    assert "pitch-analyzer.js" not in js and "pitch-meter.js" not in js
    # the mic-scoring deps are gone from the player-core wiring; getSemitonesLabel is injected there.
    assert "initMicScoring: _initMicScoring" not in js
    assert "getSemitonesLabel" in js
