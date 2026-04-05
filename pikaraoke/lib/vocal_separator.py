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


def _parse_lrc_line(line: str) -> tuple[float, str] | None:
    """Parse an LRC timestamp line like '[01:23.45]lyrics text'."""
    import re

    m = re.match(r"\[(\d+):(\d+)\.(\d+)\](.*)", line.strip())
    if not m:
        return None
    minutes, seconds, centis, text = m.groups()
    timestamp = int(minutes) * 60 + int(seconds) + int(centis) / 100
    return timestamp, text.strip()


def _clean_search_title(title: str) -> str:
    """Clean YouTube video title to extract artist + song name for lyrics search."""
    import re

    # Remove YouTube ID suffix (---xxxxx)
    title = re.sub(r"---[\w-]{11}(\.\w+)?$", "", title)
    # Remove file extension
    title = re.sub(r"\.\w{3,4}$", "", title)
    # Remove common noise words
    noise = [
        r"\(?official\s*(music\s*)?video\)?",
        r"\(?official\s*MV\)?",
        r"\(?MV\)?",
        r"\(?HQ\)?",
        r"官方版",
        r"官方MV",
        r"完整版",
        r"lyrics?\s*video",
        r"with\s*lyrics",
        r"full\s*version",
        r"\(?HD\)?",
        r"\(?4K\)?",
        r"\(?1080p\)?",
    ]
    for pat in noise:
        title = re.sub(pat, "", title, flags=re.IGNORECASE)
    # Remove brackets with content like 〈...〉【...】(...)
    title = re.sub(r"[〈〉【】\[\]]", " ", title)
    # Clean up whitespace
    title = re.sub(r"\s+", " ", title).strip()
    # Remove trailing punctuation
    title = title.rstrip(" -_")
    return title


def _search_online_lyrics(title: str) -> list[dict] | None:
    """Search for synced lyrics (LRC) online. Returns parsed segments or None."""
    try:
        import syncedlyrics

        clean_title = _clean_search_title(title)
        logging.info("Searching online lyrics for: '%s'", clean_title)
        lrc = syncedlyrics.search(clean_title, synced_only=True)
        if not lrc:
            return None

        segments = []
        lines = [_parse_lrc_line(ln) for ln in lrc.splitlines() if ln.strip()]
        parsed = [p for p in lines if p and p[1]]

        # Validation: reject if too few lines (likely wrong match)
        if len(parsed) < 5:
            logging.warning("Online lyrics too short (%d lines), skipping", len(parsed))
            return None

        for i, (start, text) in enumerate(parsed):
            end = parsed[i + 1][0] if i + 1 < len(parsed) else start + 5.0
            segments.append({"start": start, "end": end, "text": text, "words": []})

        logging.info("Found online synced lyrics: %d lines for '%s'", len(segments), clean_title)
        return segments if segments else None
    except Exception as e:
        logging.warning("Online lyrics search failed: %s", e)
        return None


def _merge_online_text_with_whisper_timing(
    whisper_segments: list[dict], online_segments: list[dict]
) -> list[dict]:
    """Replace Whisper text with online lyrics while keeping Whisper's word timing.

    For each Whisper segment, find the best matching online lyric line by
    timestamp proximity, then replace the segment text. Word-level timing
    from Whisper is preserved for smooth karaoke animation.
    """
    if not online_segments:
        return whisper_segments

    # Build a list of online lyrics with timestamps for matching
    online_lines = [(seg["start"], seg["text"]) for seg in online_segments if seg["text"]]

    result = []
    for wseg in whisper_segments:
        w_start = wseg.get("start", 0)
        w_text = wseg.get("text", "").strip()
        words = wseg.get("words", [])

        # Find closest online lyric line by start time (within 5 second window)
        best_match = None
        best_dist = 5.0
        for o_start, o_text in online_lines:
            dist = abs(w_start - o_start)
            if dist < best_dist:
                best_dist = dist
                best_match = o_text

        if best_match and words:
            # Replace the segment text but keep word-level timing
            # Distribute online text characters across Whisper word timings
            online_chars = list(best_match.replace(" ", ""))
            whisper_words = [w for w in words if w.get("word", "").strip()]

            if whisper_words and online_chars:
                # Distribute characters proportionally across word slots
                chars_per_word = max(1, len(online_chars) // len(whisper_words))
                new_words = []
                char_idx = 0
                for i, w in enumerate(whisper_words):
                    if i == len(whisper_words) - 1:
                        # Last word gets all remaining characters
                        chunk = "".join(online_chars[char_idx:])
                    else:
                        chunk = "".join(online_chars[char_idx : char_idx + chars_per_word])
                        char_idx += chars_per_word
                    if chunk:
                        new_words.append(
                            {
                                "word": chunk,
                                "start": w["start"],
                                "end": w["end"],
                            }
                        )

                result.append(
                    {
                        "start": wseg["start"],
                        "end": wseg["end"],
                        "text": best_match,
                        "words": new_words,
                    }
                )
                continue

        # No match or no words — keep original Whisper segment
        result.append(wseg)

    return result


def _format_ass_time(seconds: float) -> str:
    """Format seconds as ASS timestamp H:MM:SS.cc."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _correct_typos_with_online_lyrics(
    whisper_segments: list[dict], online_segments: list[dict]
) -> list[dict]:
    """Correct Whisper homophone errors using online lyrics as reference.

    Only replaces individual characters when the overall line similarity
    is high (>60%), keeping Whisper's text structure and word timing intact.
    Does NOT replace entire lines — only fixes likely typos.
    """
    from difflib import SequenceMatcher

    online_lines = [(seg["start"], seg["text"]) for seg in online_segments if seg["text"]]
    if not online_lines:
        return whisper_segments

    corrected_count = 0
    result = []
    for wseg in whisper_segments:
        w_text = wseg.get("text", "").strip()
        w_start = wseg.get("start", 0)
        words = wseg.get("words", [])

        # Find closest online line by timestamp (within 3 second window)
        best_match = None
        best_dist = 3.0
        for o_start, o_text in online_lines:
            dist = abs(w_start - o_start)
            if dist < best_dist:
                best_dist = dist
                best_match = o_text

        if not best_match or not words:
            result.append(wseg)
            continue

        # Check similarity — only correct if >60% similar (same line, minor typos)
        w_chars = w_text.replace(" ", "")
        o_chars = best_match.replace(" ", "")
        ratio = SequenceMatcher(None, w_chars, o_chars).ratio()

        if ratio < 0.6:
            # Too different — probably wrong match, keep Whisper as-is
            result.append(wseg)
            continue

        if ratio > 0.99:
            # Already identical, no correction needed
            result.append(wseg)
            continue

        # Character-level correction: replace individual wrong chars in each word
        o_idx = 0
        new_words = []
        for w in words:
            word_text = w.get("word", "").strip()
            if not word_text:
                new_words.append(w)
                continue

            corrected_word = ""
            for ch in word_text:
                if o_idx < len(o_chars) and ch != o_chars[o_idx]:
                    # Replace with online character (likely correct)
                    corrected_word += o_chars[o_idx]
                    corrected_count += 1
                elif o_idx < len(o_chars):
                    corrected_word += ch
                else:
                    corrected_word += ch
                o_idx += 1

            new_words.append(
                {
                    "word": corrected_word,
                    "start": w["start"],
                    "end": w["end"],
                }
            )

        result.append(
            {
                "start": wseg["start"],
                "end": wseg["end"],
                "text": best_match,
                "words": new_words,
            }
        )

    if corrected_count > 0:
        logging.info("Corrected %d characters with online lyrics", corrected_count)
    return result


def _filter_whisper_hallucinations(segments: list[dict]) -> list[dict]:
    """Filter out Whisper hallucinated segments (fake text during silence).

    Common hallucinations: repeated text, composer/lyricist credits,
    nonsensical repetitions during instrumental intros.
    """
    import re

    filtered = []
    seen_texts: dict[str, int] = {}

    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue

        # Skip very short segments (likely noise)
        duration = seg.get("end", 0) - seg.get("start", 0)
        if duration < 0.1:
            continue

        # Skip segments with high no_speech_prob (if available)
        if seg.get("no_speech_prob", 0) > 0.7:
            continue

        # Track repeated text — hallucination often repeats the same phrase
        normalized = re.sub(r"\s+", "", text)
        seen_texts[normalized] = seen_texts.get(normalized, 0) + 1
        if seen_texts[normalized] > 4:
            continue

        # Skip common hallucination patterns (credits, attributions)
        hallucination_patterns = [
            r"^[\s]*[作詞詞曲編][:：]",  # 作詞: / 作曲: / 編曲:
            r"^[\s]*[Ll]yrics?\s*[:：]",
            r"^[\s]*[Cc]omposed?\s*[:：]",
            r"^[\s]*[Mm]usic\s*[:：]",
        ]
        if any(re.match(pat, text) for pat in hallucination_patterns):
            continue

        filtered.append(seg)

    return filtered


def _to_traditional_chinese(text: str) -> str:
    """Convert simplified Chinese to traditional Chinese."""
    try:
        from opencc import OpenCC

        cc = OpenCC("s2t")
        return cc.convert(text)
    except ImportError:
        return text


def generate_karaoke_ass(segments: list[dict], title: str = "", timing_offset: float = -0.3) -> str:
    """Generate ASS subtitle content with karaoke timing tags.

    Args:
        segments: List of Whisper segments, each with 'words' containing
                  {'word': str, 'start': float, 'end': float}.
        title: Song title for the script info.
        timing_offset: Seconds to delay subtitle fill animation (positive = later).
                       Compensates for Whisper detecting word onsets slightly early.

    Returns:
        Complete ASS file content as a string.
    """
    header = f"""[Script Info]
Title: {title}
ScriptType: v4.00+
PlayResX: 3840
PlayResY: 2160
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,Arial,168,&H0000D7FF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,2,0,1,8,5,2,80,80,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header.strip()]

    # Pre-display: show lyrics 1.5s before singing starts
    # Timing offset: delay fill animation to match actual vocal onset
    pre_display = 1.5

    for segment in segments:
        words = segment.get("words", [])
        if not words:
            text = _to_traditional_chinese(segment.get("text", "").strip())
            if not text:
                continue
            start = segment.get("start", 0.0) + timing_offset
            end = segment.get("end", start + 1.0) + timing_offset
            duration_cs = max(int((end - start) * 100), 10)
            early_start = max(0, start - pre_display)
            pad_cs = int((start - early_start) * 100)
            ass_start = _format_ass_time(early_start)
            ass_end = _format_ass_time(end + 0.5)
            if pad_cs > 0:
                lines.append(
                    f"Dialogue: 0,{ass_start},{ass_end},Karaoke,,0,0,0,,"
                    f"{{\\kf{pad_cs}}}{{\\kf{duration_cs}}}{text}"
                )
            else:
                lines.append(
                    f"Dialogue: 0,{ass_start},{ass_end},Karaoke,,0,0,0,,{{\\kf{duration_cs}}}{text}"
                )
            continue

        # Build karaoke line from word-level timestamps (with offset)
        seg_start = words[0]["start"] + timing_offset
        seg_end = words[-1]["end"] + timing_offset
        early_start = max(0, seg_start - pre_display)
        pad_cs = int((seg_start - early_start) * 100)
        ass_start = _format_ass_time(early_start)
        ass_end = _format_ass_time(seg_end + 0.5)

        karaoke_parts = []
        if pad_cs > 0:
            karaoke_parts.append(f"{{\\kf{pad_cs}}}")
        for word_info in words:
            word = word_info.get("word", "").strip()
            if not word:
                continue
            w_start = word_info.get("start", 0.0) + timing_offset
            w_end = word_info.get("end", w_start + 0.1) + timing_offset
            duration_cs = max(int((w_end - w_start) * 100), 10)
            prefix = " " if len(karaoke_parts) > (1 if pad_cs > 0 else 0) else ""
            word = _to_traditional_chinese(word)
            karaoke_parts.append(f"{{\\kf{duration_cs}}}{prefix}{word}")

        if karaoke_parts:
            text = "".join(karaoke_parts)
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

            # Auto-detect CUDA at runtime
            device = self._device
            try:
                import torch

                if device == "cuda" and not torch.cuda.is_available():
                    logging.warning("CUDA not available for Demucs, using CPU")
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
                "--mp3",
                "--mp3-bitrate",
                "192",
                "-o",
                song_dir,
                song_path,
            ]

            # First run downloads model (~80MB), allow extra time
            logging.info("Running demucs (device=%s)...", device)
            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=900,
                env=env,
                encoding="utf-8",
                errors="replace",
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
        return None

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
            import warnings

            warnings.filterwarnings("ignore", message=".*Triton.*")
            # Cache model globally to avoid reloading 400MB per song
            cache_key = f"{self._whisper_model}_{device}"
            if not hasattr(VocalSeparator, "_whisper_cache"):
                VocalSeparator._whisper_cache = {}
            if cache_key not in VocalSeparator._whisper_cache:
                logging.info(
                    "Loading Whisper model '%s' on %s (first time)...", self._whisper_model, device
                )
                VocalSeparator._whisper_cache[cache_key] = whisper.load_model(
                    self._whisper_model, device=device
                )
            model = VocalSeparator._whisper_cache[cache_key]

            # Detect language from filename to avoid misidentification
            detected_lang = self._detect_language_from_filename(song_path)
            transcribe_kwargs: dict[str, object] = {
                "word_timestamps": True,
                "verbose": False,
                "condition_on_previous_text": False,
            }
            if detected_lang:
                transcribe_kwargs["language"] = detected_lang
                logging.info("Language hint from filename: %s", detected_lang)

            result = model.transcribe(audio_source, **transcribe_kwargs)

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

            # Step 2: Always use Whisper for word-level timing (smooth animation)
            # Then optionally correct text with online lyrics
            if WHISPER_AVAILABLE:
                trans_result = self.transcribe(song_path)
                if trans_result.success and trans_result.segments:
                    language = trans_result.language
                    segments = _filter_whisper_hallucinations(trans_result.segments)

                    # Try online lyrics for typo correction (character-level only)
                    search_title = title or os.path.basename(song_path)
                    online_segments = _search_online_lyrics(search_title)
                    if online_segments:
                        segments = _correct_typos_with_online_lyrics(segments, online_segments)

                    ass_content = generate_karaoke_ass(segments, title)
                    ass_path = _ass_path_for(song_path)
                    with open(ass_path, "w", encoding="utf-8") as f:
                        f.write(ass_content)
                    logging.info("Karaoke ASS generated: %s", ass_path)
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
