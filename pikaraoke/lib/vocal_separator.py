"""AI-powered vocal separation, transcription, and karaoke lyrics generation.

Uses Demucs for vocal/instrumental separation and Whisper for word-level
transcription. Generates ASS subtitle files with karaoke timing tags (kf)
that SubtitlesOctopus/libass renders as left-to-right color-changing lyrics.

All AI dependencies (demucs, whisper, torch) are optional. The module
gracefully degrades when they are not installed.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from pikaraoke.lib.events import EventSystem

# Lazy-check for optional dependencies
DEMUCS_AVAILABLE = False
WHISPER_AVAILABLE = False

try:
    import demucs  # noqa: F401

    DEMUCS_AVAILABLE = True
except ImportError:
    pass

try:
    import whisper  # noqa: F401

    WHISPER_AVAILABLE = True
except ImportError:
    pass


@dataclass
class StemPaths:
    """Paths to separated audio stems."""

    vocals: str
    instrumental: str


@dataclass
class SeparationResult:
    """Result of vocal separation."""

    success: bool
    stem_paths: StemPaths | None = None
    error: str | None = None


@dataclass
class TranscriptionResult:
    """Result of Whisper transcription with word-level timestamps."""

    success: bool
    segments: list[dict] = field(default_factory=list)
    language: str = ""
    error: str | None = None


@dataclass
class ProcessResult:
    """Result of the full processing pipeline."""

    success: bool
    stem_paths: StemPaths | None = None
    ass_path: str | None = None
    language: str = ""
    error: str | None = None


def _stem_paths_for(song_path: str) -> tuple[str, str]:
    """Compute expected stem file paths for a song."""
    base = os.path.splitext(song_path)[0]
    return base + "_vocals.mp3", base + "_instrumental.mp3"


def _ass_path_for(song_path: str) -> str:
    """Compute expected karaoke ASS path for a song."""
    base = os.path.splitext(song_path)[0]
    return base + "_karaoke.ass"


def _format_ass_time(seconds: float) -> str:
    """Format seconds as ASS timestamp H:MM:SS.cc."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def generate_karaoke_ass(segments: list[dict], title: str = "") -> str:
    """Generate ASS subtitle content with karaoke timing tags.

    Args:
        segments: List of Whisper segments, each with 'words' containing
                  {'word': str, 'start': float, 'end': float}.
        title: Song title for the script info.

    Returns:
        Complete ASS file content as a string.
    """
    header = f"""[Script Info]
Title: {title}
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,Arial,58,&H0000FFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3,1,2,40,40,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header.strip()]

    for segment in segments:
        words = segment.get("words", [])
        if not words:
            # Fallback: treat entire segment text as one block
            text = segment.get("text", "").strip()
            if not text:
                continue
            start = segment.get("start", 0.0)
            end = segment.get("end", start + 1.0)
            duration_cs = max(int((end - start) * 100), 10)
            ass_start = _format_ass_time(start)
            ass_end = _format_ass_time(end)
            lines.append(
                f"Dialogue: 0,{ass_start},{ass_end},Karaoke,,0,0,0,,{{\\kf{duration_cs}}}{text}"
            )
            continue

        # Build karaoke line from word-level timestamps
        seg_start = words[0]["start"]
        seg_end = words[-1]["end"]
        ass_start = _format_ass_time(seg_start)
        ass_end = _format_ass_time(seg_end + 0.5)  # Small buffer

        karaoke_parts = []
        for word_info in words:
            word = word_info.get("word", "").strip()
            if not word:
                continue
            w_start = word_info.get("start", 0.0)
            w_end = word_info.get("end", w_start + 0.1)
            duration_cs = max(int((w_end - w_start) * 100), 5)
            karaoke_parts.append(f"{{\\kf{duration_cs}}}{word}")

        if karaoke_parts:
            text = " ".join(karaoke_parts)
            lines.append(f"Dialogue: 0,{ass_start},{ass_end},Karaoke,,0,0,0,,{text}")

    return "\n".join(lines) + "\n"


class VocalSeparator:
    """Manages vocal separation, transcription, and karaoke ASS generation.

    All operations run as background tasks in a worker thread to avoid
    blocking the Flask server. Progress is reported via EventSystem.
    """

    def __init__(
        self,
        events: EventSystem,
        download_path: str,
        device: str = "cuda",
        whisper_model: str = "medium",
    ) -> None:
        self._events = events
        self._download_path = download_path
        self._device = device
        self._whisper_model = whisper_model
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        """Check if vocal separation dependencies are installed."""
        return DEMUCS_AVAILABLE

    def is_whisper_available(self) -> bool:
        """Check if Whisper transcription is available."""
        return WHISPER_AVAILABLE

    def has_stems(self, song_path: str) -> bool:
        """Check if separated stems exist for a song."""
        vocals_path, instrumental_path = _stem_paths_for(song_path)
        return os.path.exists(vocals_path) and os.path.exists(instrumental_path)

    def has_karaoke_ass(self, song_path: str) -> bool:
        """Check if a karaoke ASS file exists for a song."""
        return os.path.exists(_ass_path_for(song_path))

    def get_stem_paths(self, song_path: str) -> StemPaths | None:
        """Get stem paths if they exist."""
        vocals_path, instrumental_path = _stem_paths_for(song_path)
        if os.path.exists(vocals_path) and os.path.exists(instrumental_path):
            return StemPaths(vocals=vocals_path, instrumental=instrumental_path)
        return None

    def separate(self, song_path: str) -> SeparationResult:
        """Run Demucs two-stem separation. Produces _vocals.mp3 and _instrumental.mp3."""
        if not DEMUCS_AVAILABLE:
            return SeparationResult(success=False, error="Demucs is not installed")

        if self.has_stems(song_path):
            stems = self.get_stem_paths(song_path)
            return SeparationResult(success=True, stem_paths=stems)

        vocals_path, instrumental_path = _stem_paths_for(song_path)
        song_dir = os.path.dirname(song_path)

        try:
            self._events.emit("separation_started", {"song_path": song_path})
            logging.info("Starting vocal separation: %s", song_path)

            cmd = [
                sys.executable,
                "-m",
                "demucs",
                "--two-stems",
                "vocals",
                "-d",
                self._device,
                "--mp3",
                "--mp3-bitrate",
                "192",
                "-o",
                song_dir,
                song_path,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )

            if result.returncode != 0:
                error = result.stderr[:500] if result.stderr else "Unknown error"
                logging.error("Demucs failed: %s", error)

                # Retry with CPU if CUDA failed
                if self._device == "cuda" and "CUDA" in error:
                    logging.warning("CUDA failed, retrying with CPU...")
                    cmd[cmd.index("cuda")] = "cpu"
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
                    if result.returncode != 0:
                        return SeparationResult(success=False, error="Demucs failed on CPU too")
                else:
                    return SeparationResult(success=False, error=error)

            # Demucs outputs to <output_dir>/htdemucs/<stem_name>/
            song_stem = Path(song_path).stem
            demucs_dir = os.path.join(song_dir, "htdemucs", song_stem)

            # Find output files (could be .mp3 or .wav)
            for ext in (".mp3", ".wav"):
                v_src = os.path.join(demucs_dir, f"vocals{ext}")
                n_src = os.path.join(demucs_dir, f"no_vocals{ext}")
                if os.path.exists(v_src) and os.path.exists(n_src):
                    os.rename(v_src, vocals_path)
                    os.rename(n_src, instrumental_path)
                    break
            else:
                return SeparationResult(success=False, error="Demucs output files not found")

            # Cleanup demucs temp directory
            import shutil

            htdemucs_dir = os.path.join(song_dir, "htdemucs")
            if os.path.isdir(htdemucs_dir):
                shutil.rmtree(htdemucs_dir, ignore_errors=True)

            logging.info("Vocal separation complete: %s", song_path)
            self._events.emit("separation_complete", {"song_path": song_path})

            return SeparationResult(
                success=True,
                stem_paths=StemPaths(vocals=vocals_path, instrumental=instrumental_path),
            )

        except subprocess.TimeoutExpired:
            return SeparationResult(success=False, error="Demucs timed out (10 min)")
        except FileNotFoundError:
            return SeparationResult(
                success=False, error="Demucs command not found — is it installed?"
            )
        except OSError as e:
            return SeparationResult(success=False, error=str(e))

    def transcribe(self, song_path: str) -> TranscriptionResult:
        """Run Whisper transcription on the vocals stem for word-level timestamps."""
        if not WHISPER_AVAILABLE:
            return TranscriptionResult(success=False, error="Whisper is not installed")

        vocals_path, _ = _stem_paths_for(song_path)
        audio_source = vocals_path if os.path.exists(vocals_path) else song_path

        try:
            logging.info("Starting transcription: %s", audio_source)
            import torch
            import whisper

            device = self._device
            if device == "cuda" and not torch.cuda.is_available():
                logging.warning("CUDA not available for Whisper, falling back to CPU")
                device = "cpu"
            model = whisper.load_model(self._whisper_model, device=device)
            result = model.transcribe(
                audio_source,
                word_timestamps=True,
                verbose=False,
            )

            segments = []
            for seg in result.get("segments", []):
                segment_data = {
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg["text"],
                    "words": seg.get("words", []),
                }
                segments.append(segment_data)

            language = result.get("language", "")
            logging.info(
                "Transcription complete: %d segments, language=%s", len(segments), language
            )
            return TranscriptionResult(success=True, segments=segments, language=language)

        except Exception as e:
            logging.error("Whisper transcription failed: %s", e)
            return TranscriptionResult(success=False, error=str(e))

    def process(self, song_path: str, title: str = "") -> ProcessResult:
        """Full pipeline: separate → transcribe → generate karaoke ASS.

        Runs all steps sequentially. Each step is optional — if separation
        fails, transcription still runs on the original file.
        """
        with self._lock:
            stem_paths = None
            ass_path = None
            language = ""

            # Step 1: Vocal separation (Demucs)
            if DEMUCS_AVAILABLE:
                sep_result = self.separate(song_path)
                if sep_result.success:
                    stem_paths = sep_result.stem_paths
                else:
                    logging.warning("Separation failed for %s: %s", song_path, sep_result.error)

            # Step 2: Transcription (Whisper)
            if WHISPER_AVAILABLE:
                trans_result = self.transcribe(song_path)
                if trans_result.success and trans_result.segments:
                    language = trans_result.language

                    # Step 3: Generate karaoke ASS
                    ass_content = generate_karaoke_ass(trans_result.segments, title)
                    ass_path = _ass_path_for(song_path)
                    with open(ass_path, "w", encoding="utf-8") as f:
                        f.write(ass_content)
                    logging.info("Karaoke ASS generated: %s", ass_path)
                else:
                    logging.warning(
                        "Transcription failed for %s: %s",
                        song_path,
                        trans_result.error,
                    )

            success = stem_paths is not None or ass_path is not None
            return ProcessResult(
                success=success,
                stem_paths=stem_paths,
                ass_path=ass_path,
                language=language,
            )
