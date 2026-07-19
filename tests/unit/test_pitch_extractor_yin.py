"""P1.5-1: the reference-pitch YIN must be a fast, importable numpy function (was pure-Python
nested loops inside a `python -c` string — minutes of CPU per song, risking the 300s timeout and
losing the scoring curve). Unit-tested here directly with synthetic tones."""

import pytest


def test_yin_detects_a_known_tone():
    np = pytest.importorskip("numpy")
    from pikaraoke.lib.pitch_extractor import _yin_pitch

    sr = 16000
    freq = 220.0  # A3, well inside the 80-1100 Hz vocal band
    t = np.arange(sr, dtype=np.float32) / sr  # 1 second
    samples = (0.6 * np.sin(2 * np.pi * freq * t)).astype(np.float32)

    curve = _yin_pitch(samples, sr, 0.05)
    assert curve, "should produce hop-spaced results"
    pitches = [p["pitch"] for p in curve if p["pitch"] > 0]
    assert pitches, "should detect the tone (nonzero pitch)"
    median = sorted(pitches)[len(pitches) // 2]
    assert abs(median - freq) < 5, f"detected ~{median} Hz, expected ~{freq} Hz"


def test_yin_reports_zero_on_silence():
    np = pytest.importorskip("numpy")
    from pikaraoke.lib.pitch_extractor import _yin_pitch

    sr = 16000
    samples = np.zeros(sr, dtype=np.float32)
    curve = _yin_pitch(samples, sr, 0.05)
    assert curve
    # Silence must not yield NaN/garbage pitches; all entries are the 0 sentinel.
    assert all(p["pitch"] == 0 for p in curve)


def test_yin_detects_a_higher_tone():
    np = pytest.importorskip("numpy")
    from pikaraoke.lib.pitch_extractor import _yin_pitch

    sr = 16000
    freq = 440.0  # A4
    t = np.arange(sr, dtype=np.float32) / sr
    samples = (0.6 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    curve = _yin_pitch(samples, sr, 0.05)
    pitches = [p["pitch"] for p in curve if p["pitch"] > 0]
    assert pitches
    median = sorted(pitches)[len(pitches) // 2]
    assert abs(median - freq) < 8, f"detected ~{median} Hz, expected ~{freq} Hz"
