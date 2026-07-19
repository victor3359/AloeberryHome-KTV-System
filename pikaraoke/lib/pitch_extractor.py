"""Extract reference pitch curve from vocal audio for singing scoring.

Uses YIN algorithm to detect F0 (fundamental frequency) from the
separated vocal stem. Outputs a JSON file with timestamp-pitch pairs
that the frontend uses as the "correct" melody for scoring.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys


def _read_audio_pcm(path: str):
    """Decode audio to mono 16 kHz float32 samples via ffmpeg. Returns (samples, sample_rate),
    or (None, 0) if ffmpeg fails. Uses np.frombuffer instead of a per-sample struct.unpack loop.
    """
    import numpy as np

    cmd = ["ffmpeg", "-i", path, "-f", "s16le", "-ac", "1", "-ar", "16000", "-"]
    proc = subprocess.run(cmd, capture_output=True, timeout=120)
    if proc.returncode != 0 or not proc.stdout:
        return None, 0
    samples = np.frombuffer(proc.stdout, dtype="<i2").astype(np.float32) / 32768.0
    return samples, 16000


def _yin_pitch(samples, sr: int, hop: float) -> list[dict]:
    """Vectorized YIN F0 estimation over hop-spaced 40ms windows.

    Returns [{time, pitch, confidence}], with pitch=0 where none is found. tau is limited to the
    80-1100 Hz vocal band and the difference-function inner sum is a numpy dot, replacing the
    O(window^2) pure-Python double loop that took minutes per song.
    """
    import numpy as np

    win = int(sr * 0.04)  # 40ms window
    hop_samples = max(1, int(sr * hop))
    threshold = 0.15
    tau_max = min(win - 1, int(sr / 80) + 1)  # lowest scored pitch (80 Hz)
    tau_min = max(2, int(sr / 1100))  # highest scored pitch (1100 Hz)
    results: list[dict] = []
    limit = len(samples) - win * 2
    for start in range(0, max(0, limit), hop_samples):
        buf = samples[start : start + win * 2]
        head = buf[:win]
        d = np.empty(tau_max + 1, dtype=np.float64)
        d[0] = 0.0
        for tau in range(1, tau_max + 1):
            diff = head - buf[tau : tau + win]
            d[tau] = float(np.dot(diff, diff))
        cumsum = np.cumsum(d[1:])
        taus = np.arange(1, tau_max + 1)
        d2 = np.ones(tau_max + 1, dtype=np.float64)
        nz = cumsum > 0
        d2[1:][nz] = d[1:][nz] * taus[nz] / cumsum[nz]
        tau_est = -1
        below = np.where(d2[tau_min : tau_max + 1] < threshold)[0]
        if len(below):
            tau = int(below[0]) + tau_min
            while tau + 1 <= tau_max and d2[tau + 1] < d2[tau]:
                tau += 1
            tau_est = tau
        t = round(start / sr, 3)
        if tau_est > 0:
            pitch = sr / tau_est
            if 80 <= pitch <= 1100:
                conf = 1.0 - d2[tau_est]
                results.append(
                    {
                        "time": t,
                        "pitch": round(float(pitch), 1),
                        "confidence": round(float(conf), 2),
                    }
                )
                continue
        results.append({"time": t, "pitch": 0, "confidence": 0})
    return results


def extract_pitch(
    audio_path: str, output_path: str | None = None, hop_size: float = 0.05
) -> str | None:
    """Extract pitch curve from audio file using a subprocess.

    Args:
        audio_path: Path to the audio file (typically _vocals.mp3).
        output_path: Path for output JSON. Defaults to <base>_pitch.json.
        hop_size: Time between pitch samples in seconds (default 50ms = 20 updates/sec).

    Returns:
        Path to the generated JSON file, or None on failure.
    """
    if not os.path.exists(audio_path):
        return None

    if output_path is None:
        base = os.path.splitext(audio_path)[0]
        # Remove _vocals suffix if present
        if base.endswith("_vocals"):
            base = base[: -len("_vocals")]
        output_path = base + "_pitch.json"

    if os.path.exists(output_path):
        logging.info("Pitch curve already exists: %s", output_path)
        return output_path

    logging.info("Extracting pitch curve from: %s", audio_path)

    # Run pitch extraction in a subprocess to keep the CPU-heavy YIN off the gevent event loop.
    # The heavy lifting is the numpy _read_audio_pcm/_yin_pitch functions imported here.
    script = (
        "import sys, json, os\n"
        "from pikaraoke.lib.pitch_extractor import _read_audio_pcm, _yin_pitch\n"
        "samples, sr = _read_audio_pcm(sys.argv[1])\n"
        "if samples is not None and len(samples):\n"
        "    curve = _yin_pitch(samples, sr, float(sys.argv[3]))\n"
        "    # Atomic write: a crash mid-dump must not leave a truncated JSON that is then\n"
        "    # served and cached forever.\n"
        "    tmp = sys.argv[2] + '.tmp'\n"
        "    json.dump(curve, open(tmp, 'w'), ensure_ascii=False)\n"
        "    os.replace(tmp, sys.argv[2])\n"
        "    print(f'Extracted {len(curve)} pitch points')\n"
        "else:\n"
        "    print('Failed to read audio')\n"
        "    sys.exit(1)\n"
    )

    try:
        creationflags = 0x00004000 if sys.platform == "win32" else 0
        result = subprocess.run(
            [sys.executable, "-c", script, audio_path, output_path, str(hop_size)],
            capture_output=True,
            text=True,
            timeout=300,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )

        if result.returncode == 0 and os.path.exists(output_path):
            logging.info("Pitch curve extracted: %s", output_path)
            return output_path

        logging.warning("Pitch extraction failed: %s", result.stderr[:200])
        return None

    except subprocess.TimeoutExpired:
        logging.warning("Pitch extraction timed out")
        return None
    except OSError as e:
        logging.warning("Pitch extraction error: %s", e)
        return None
