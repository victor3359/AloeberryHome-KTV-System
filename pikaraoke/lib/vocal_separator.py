"""AI-powered vocal separation, transcription, and karaoke lyrics generation.

Uses Demucs for vocal/instrumental separation and Whisper for word-level
transcription. Generates ASS subtitle files with karaoke timing tags (kf)
that SubtitlesOctopus/libass renders as left-to-right color-changing lyrics.

All AI dependencies (demucs, whisper, torch) are optional. The module
gracefully degrades when they are not installed.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from pikaraoke.lib.events import EventSystem
from pikaraoke.lib.karaoke_subtitle import (  # noqa: F401  (re-exported for backward compat)
    _filter_whisper_hallucinations,
    _format_ass_time,
    generate_karaoke_ass,
)
from pikaraoke.lib.lyrics_corrector import (  # noqa: F401  (re-exported for backward compat)
    _clean_search_title,
    _correct_typos_with_online_lyrics,
    _parse_lrc_line,
    _search_online_lyrics,
)

# Lazy-check for optional dependencies
DEMUCS_AVAILABLE = False
WHISPER_AVAILABLE = False

try:
    import demucs  # noqa: F401

    DEMUCS_AVAILABLE = True
except ImportError:
    pass

try:
    import faster_whisper  # noqa: F401

    WHISPER_AVAILABLE = True
except ImportError:
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

            # Use GPU if available (subprocess isolates from Flask/browser)
            device = self._device
            try:
                import torch

                if device == "cuda" and not torch.cuda.is_available():
                    device = "cpu"
            except ImportError:
                device = "cpu"

            cmd = [
                sys.executable,
                "-m",
                "demucs",
                "--two-stems",
                "vocals",
                "-d",
                device,
                "--segment",
                "7",  # Process 7s chunks (htdemucs max is 7.8s)
                "--mp3",
                "--mp3-bitrate",
                "192",
                "-o",
                song_dir,
                song_path,
            ]

            # First run downloads model (~80MB), allow extra time
            logging.info("Running demucs (device=%s)...", device)
            env = {
                **os.environ,
                "PYTHONIOENCODING": "utf-8",
                "OMP_NUM_THREADS": "10",
                "MKL_NUM_THREADS": "10",
            }
            # Lower priority on Windows so playback isn't starved
            creationflags = 0x00004000 if sys.platform == "win32" else 0
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=900,
                env=env,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )

            if result.returncode != 0:
                # Filter progress bars from stderr to find real errors
                stderr_lines = (result.stderr or "").splitlines()
                error_lines = [
                    ln
                    for ln in stderr_lines
                    if ln.strip()
                    and "B/s]" not in ln
                    and "it/s]" not in ln
                    and not ln.strip().startswith(("%", "|"))
                ]
                error = "\n".join(error_lines[-10:]) if error_lines else result.stderr[:500]
                logging.error("Demucs failed (exit %d): %s", result.returncode, error)
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

    @staticmethod
    def _detect_language_from_filename(song_path: str) -> str | None:
        """Detect language from filename Unicode characters."""
        import re

        name = os.path.basename(song_path)
        if re.search(r"[\u3040-\u30ff]", name):
            return "ja"
        if re.search(r"[\uac00-\ud7af]", name):
            return "ko"
        if re.search(r"[\u4e00-\u9fff]", name):
            return "zh"
        # Vietnamese: Latin with unique diacritics (ơ ư ă đ ờ ị ứ ề ộ ả etc.)
        if re.search(r"[\u01a0\u01a1\u01af\u01b0\u0102\u0103\u0110\u0111]", name):
            return "vi"
        if re.search(r"[\u1ea0-\u1ef9]", name):
            return "vi"
        return None

    def transcribe(self, song_path: str) -> TranscriptionResult:
        """Run Whisper transcription as a subprocess to avoid GIL contention with Flask."""
        if not WHISPER_AVAILABLE:
            return TranscriptionResult(success=False, error="Whisper is not installed")

        vocals_path, _ = _stem_paths_for(song_path)
        audio_source = vocals_path if os.path.exists(vocals_path) else song_path

        try:
            logging.info("Starting transcription: %s", audio_source)
            detected_lang = self._detect_language_from_filename(song_path)

            # Run Whisper in a subprocess to avoid GIL contention with Flask/gevent.
            # In-process Whisper with 10 PyTorch threads starved the main thread.
            import json as _json
            import tempfile

            output_file = tempfile.mktemp(suffix=".json")
            lang_arg = f"'{detected_lang}'" if detected_lang else "None"
            # Use faster-whisper (CTranslate2) if available, fallback to openai-whisper
            script = (
                "import sys, json, warnings, os\n"
                "warnings.filterwarnings('ignore')\n"
                "os.environ['OMP_NUM_THREADS'] = '10'\n"
                "try:\n"
                "    from faster_whisper import WhisperModel\n"
                f"    model = WhisperModel('{self._whisper_model}', device='cpu', compute_type='int8', cpu_threads=10)\n"
                f"    segs_iter, info = model.transcribe(sys.argv[1], word_timestamps=True, condition_on_previous_text=False, language={lang_arg})\n"
                "    segs = []\n"
                "    for s in segs_iter:\n"
                "        words = [dict(word=w.word, start=w.start, end=w.end) for w in (s.words or [])]\n"
                "        segs.append(dict(start=s.start, end=s.end, text=s.text, words=words, no_speech_prob=s.no_speech_prob))\n"
                "    lang = info.language\n"
                "except ImportError:\n"
                "    import torch; torch.set_num_threads(10)\n"
                "    import whisper\n"
                f"    model = whisper.load_model('{self._whisper_model}', device='cpu')\n"
                f"    r = model.transcribe(sys.argv[1], word_timestamps=True, verbose=False, condition_on_previous_text=False"
                + (f", language='{detected_lang}'" if detected_lang else "")
                + ")\n"
                "    segs = [dict(start=s['start'],end=s['end'],text=s['text'],words=s.get('words',[]),no_speech_prob=s.get('no_speech_prob',0)) for s in r.get('segments',[])]\n"
                "    lang = r.get('language', '')\n"
                "json.dump(dict(segments=segs, language=lang), open(sys.argv[2], 'w', encoding='utf-8'), ensure_ascii=False)\n"
            )

            if detected_lang:
                logging.info("Language hint from filename: %s", detected_lang)

            env = {
                **os.environ,
                "PYTHONIOENCODING": "utf-8",
                "OMP_NUM_THREADS": "10",
                "MKL_NUM_THREADS": "10",
            }
            creationflags = 0x00004000 if sys.platform == "win32" else 0
            proc = subprocess.run(
                [sys.executable, "-c", script, audio_source, output_file],
                capture_output=True,
                text=True,
                timeout=600,
                env=env,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )

            if proc.returncode != 0 or not os.path.exists(output_file):
                error = proc.stderr[:500] if proc.stderr else "Whisper subprocess failed"
                logging.error("Whisper failed: %s", error)
                return TranscriptionResult(success=False, error=error)

            with open(output_file, encoding="utf-8") as f:
                data = _json.load(f)
            os.remove(output_file)

            segments = []
            for seg in data.get("segments", []):
                segment_data = {
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg["text"],
                    "words": seg.get("words", []),
                    "no_speech_prob": seg.get("no_speech_prob", 0),
                }
                segments.append(segment_data)

            language = data.get("language", "")
            logging.info(
                "Transcription complete: %d segments, language=%s", len(segments), language
            )
            return TranscriptionResult(success=True, segments=segments, language=language)

        except (
            subprocess.SubprocessError,
            OSError,
            json.JSONDecodeError,
            KeyError,
            ValueError,
        ) as e:
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

            # Step 1: Vocal separation (Demucs) — 0-50%
            if DEMUCS_AVAILABLE:
                self._events.emit("processing_progress", {"stage": "分離人聲", "percent": 0})
                sep_result = self.separate(song_path)
                if sep_result.success:
                    stem_paths = sep_result.stem_paths
                    self._events.emit("processing_progress", {"stage": "分離完成", "percent": 50})
                else:
                    logging.warning("Separation failed for %s: %s", song_path, sep_result.error)
                    self._events.emit(
                        "processing_progress", {"stage": "分離失敗，改用原始音訊", "percent": 50}
                    )

            # Step 2: Whisper transcription — 50-90%
            if WHISPER_AVAILABLE:
                self._events.emit("processing_progress", {"stage": "AI 生成歌詞中", "percent": 55})
                trans_result = self.transcribe(song_path)
                if trans_result.success and trans_result.segments:
                    language = trans_result.language
                    self._events.emit("processing_progress", {"stage": "歌詞校對中", "percent": 85})
                    segments = _filter_whisper_hallucinations(trans_result.segments)

                    # Try online lyrics for typo correction (character-level only)
                    search_title = title or os.path.basename(song_path)
                    online_segments = _search_online_lyrics(search_title)
                    if online_segments:
                        segments = _correct_typos_with_online_lyrics(segments, online_segments)

                    self._events.emit("processing_progress", {"stage": "產生字幕", "percent": 95})
                    ass_content = generate_karaoke_ass(segments, title)
                    ass_path = _ass_path_for(song_path)
                    with open(ass_path, "w", encoding="utf-8") as f:
                        f.write(ass_content)
                    logging.info("Karaoke ASS generated: %s", ass_path)

                    # Step 3: Extract reference pitch curve for scoring
                    self._events.emit("processing_progress", {"stage": "提取參考音高", "percent": 96})
                    try:
                        from pikaraoke.lib.pitch_extractor import extract_pitch

                        vocals_for_pitch, _ = _stem_paths_for(song_path)
                        if os.path.exists(vocals_for_pitch):
                            extract_pitch(vocals_for_pitch)
                    except (ImportError, subprocess.SubprocessError, OSError) as e:
                        logging.warning("Pitch extraction failed: %s", e)

                    self._events.emit("processing_progress", {"stage": "處理完成", "percent": 100})
                else:
                    logging.warning(
                        "Transcription failed for %s: %s",
                        song_path,
                        getattr(trans_result, "error", "unknown"),
                    )

            success = stem_paths is not None or ass_path is not None
            return ProcessResult(
                success=success,
                stem_paths=stem_paths,
                ass_path=ass_path,
                language=language,
            )
