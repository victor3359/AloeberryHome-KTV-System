import os
import re

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_SPLASH_JS = os.path.join(_PKG, "static", "js", "splash.js")
_PITCH_SHIFT = os.path.join(_PKG, "static", "js", "modules", "pitch-shift.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_pitch_shift_context_is_never_closed():
    """P0-1: an HTMLMediaElement can be captured by only one MediaElementSourceNode, and once
    captured its audio is permanently routed into that graph. Closing the AudioContext left #video
    routed into a dead graph, muting every later song. The context persists for the whole session
    — it is never closed. (Owned by modules/pitch-shift.js since slice 8.)"""
    mod = _read(_PITCH_SHIFT)
    assert ".close()" not in mod, "the pitch-shift context must never be torn down"
    splash = _read(_SPLASH_JS)
    assert "_pitchShiftCtx" not in splash, "pitch-shift state no longer leaks through splash"


def test_pitch_shift_module_exports_and_splash_imports():
    """Slice 8: pitch-shift is an ES module; splash imports its entrypoints and injects deps."""
    mod = _read(_PITCH_SHIFT)
    assert re.search(r"^export function initPitchShift\b", mod, re.M)
    assert re.search(r"^export function resetPitchShift\b", mod, re.M)
    assert re.search(r"^export async function applyPitchShift\b", mod, re.M)
    splash = _read(_SPLASH_JS)
    assert "initPitchShift({" in splash
    assert re.search(
        r'import \{[^}]*\binitPitchShift\b[^}]*\} from "/static/js/modules/pitch-shift\.js"', splash
    )
    # resetPitchShift/applyPitchShift are imported by player-core (slice 9), which uses them.
    pc = _read(os.path.join(_PKG, "static", "js", "modules", "player-core.js"))
    assert re.search(
        r'import \{[^}]*\bresetPitchShift\b[^}]*\} from "/static/js/modules/pitch-shift\.js"', pc
    )


def test_pitch_shift_bypasses_worklet_at_zero_semitones():
    """At 0 semitones playback routes source -> destination (native, no worklet latency); the
    worklet is spliced in only while actually shifting."""
    mod = _read(_PITCH_SHIFT)
    assert "function _route" in mod
    assert "_bypassed" in mod
