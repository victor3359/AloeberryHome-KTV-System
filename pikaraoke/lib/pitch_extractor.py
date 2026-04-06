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

    # Run pitch extraction in subprocess to avoid blocking Flask
    script = (
        "import sys, json, warnings, struct, wave, math, os\n"
        "warnings.filterwarnings('ignore')\n"
        "\n"
        "def read_audio(path):\n"
        "    import subprocess\n"
        "    # Use ffmpeg to convert to raw PCM\n"
        "    cmd = ['ffmpeg', '-i', path, '-f', 's16le', '-ac', '1', '-ar', '16000', '-']\n"
        "    p = subprocess.run(cmd, capture_output=True, timeout=120)\n"
        "    if p.returncode != 0:\n"
        "        return None, 0\n"
        "    samples = []\n"
        "    for i in range(0, len(p.stdout), 2):\n"
        "        if i + 1 < len(p.stdout):\n"
        "            val = struct.unpack('<h', p.stdout[i:i+2])[0] / 32768.0\n"
        "            samples.append(val)\n"
        "    return samples, 16000\n"
        "\n"
        "def yin_pitch(samples, sr, hop):\n"
        "    win = int(sr * 0.04)  # 40ms window\n"
        "    hop_samples = int(sr * hop)\n"
        "    results = []\n"
        "    for start in range(0, len(samples) - win * 2, hop_samples):\n"
        "        buf = samples[start:start + win * 2]\n"
        "        half = win\n"
        "        d = [0.0] * half\n"
        "        for tau in range(1, half):\n"
        "            s = 0\n"
        "            for j in range(half):\n"
        "                delta = buf[j] - buf[j + tau]\n"
        "                s += delta * delta\n"
        "            d[tau] = s\n"
        "        # CMND\n"
        "        d2 = [1.0] * half\n"
        "        rs = 0\n"
        "        for tau in range(1, half):\n"
        "            rs += d[tau]\n"
        "            d2[tau] = d[tau] * tau / rs if rs > 0 else 1\n"
        "        # Find minimum below threshold\n"
        "        tau_est = -1\n"
        "        for tau in range(2, half):\n"
        "            if d2[tau] < 0.15:\n"
        "                while tau + 1 < half and d2[tau + 1] < d2[tau]:\n"
        "                    tau += 1\n"
        "                tau_est = tau\n"
        "                break\n"
        "        if tau_est > 0:\n"
        "            pitch = sr / tau_est\n"
        "            conf = 1 - d2[tau_est]\n"
        "            if 80 <= pitch <= 1100:\n"
        "                results.append(dict(time=round(start / sr, 3), pitch=round(pitch, 1), confidence=round(conf, 2)))\n"
        "                continue\n"
        "        results.append(dict(time=round(start / sr, 3), pitch=0, confidence=0))\n"
        "    return results\n"
        "\n"
        "samples, sr = read_audio(sys.argv[1])\n"
        "if samples:\n"
        "    curve = yin_pitch(samples, sr, float(sys.argv[3]))\n"
        "    json.dump(curve, open(sys.argv[2], 'w'), ensure_ascii=False)\n"
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
    except Exception as e:
        logging.warning("Pitch extraction error: %s", e)
        return None
