# CLAUDE.md

Guidance for Claude Code when working on AloeberryHome KTV System.

## Project Overview

AloeberryHome KTV System is a professional-grade home KTV system based on PiKaraoke. It transforms YouTube official MVs into karaoke experiences with AI-powered vocal separation (Demucs GPU), auto-generated scrolling lyrics (Whisper), instant Original/KTV audio switching (HLS multi-audio), real pitch shift (AudioWorklet), and microphone-based singing scoring (YIN algorithm). Runs on Windows, macOS, Linux, and Raspberry Pi.

### Key Architecture

- **AI Pipeline**: Download -> Demucs (GPU subprocess) -> Whisper (CPU subprocess) -> Online lyrics alignment (word timeline) -> ASS two-line KTV subtitles -> SQLite metadata
- **Lyrics Pipeline**: Online lyrics (Musixmatch/Lrclib) provide text, Whisper provides per-word timestamps, global LRC-MV offset correction, hallucination filtering, OpenCC s2twp for Taiwan Traditional Chinese
- **Playback**: FFmpeg HLS multi-audio -> HLS.js -> SubtitlesOctopus -> SoundTouchJS AudioWorklet pitch shift
- **Concurrency**: RLock on 7 modules (QueueManager, PlaybackController, PlayStats, Favorites, SongList, DownloadManager, Karaoke session)
- **Subprocess isolation**: Demucs and Whisper both run as separate Python processes to avoid GIL contention with Flask/gevent
- **Modular lyrics**: `vocal_separator.py` (orchestration), `karaoke_subtitle.py` (ASS generation), `lyrics_corrector.py` (online alignment)
- **Companion files**: Songs have `_vocals.mp3`, `_instrumental.mp3`, `_karaoke.ass`, `_pitch.json` companions

## Core Principles

**Single-owner maintainability:** Code clarity over documentation. Simplicity over flexibility. One source of truth.

## Refactoring

**Refactor iteratively as you work.** When touching code:

- Extract classes when a module has multiple responsibilities (like `Browser` was extracted from utilities)
- Extract functions when logic is repeated or a function exceeds ~50 lines
- Rename unclear variables/functions immediately
- Delete dead code - never comment it out
- Update related code consistently (no half-migrations)

**When to refactor:**

- Code you're modifying is hard to understand
- You're adding a third similar pattern (rule of three)
- A function/class is doing too many things

**When NOT to refactor:**

- Unrelated code "while you're in the area"
- Working code that you're not modifying
- To add flexibility you don't need yet

## Code Style

- PEP 8, 4 spaces, meaningful names
- Type hints required: modern syntax (`str | None`) — Python 3.10+ is the minimum, no `from __future__ import annotations` needed
- Concise docstrings for public APIs - explain "why", not "how"
- No emoji or unicode emoji substitutes

## Filename Conventions

YouTube video filenames use exactly 11-character IDs:

- PiKaraoke format: `Title---dQw4w9WgXcQ.mp4` (triple dash)
- yt-dlp format: `Title [dQw4w9WgXcQ].mp4` (brackets)

Only support these two patterns.

## Error Handling

- Catch specific exceptions, never bare `except:`
- Log errors, never swallow silently
- Use context managers for resources

## Testing

- pytest with mocked external I/O and subprocess operations only
- Test business logic and integration points
- Skip trivial getters/setters
- Use real `EventSystem` and `PreferenceManager` instances (they're lightweight)

## Code Quality

```bash
# Run pre-commit checks
uv run pre-commit run --config code_quality/.pre-commit-config.yaml --all-files
```

Tools: Black (100 char), isort, pycln, pylint, mdformat.

Never commit to `main` directly.

## Pull Requests

PRs must include a test plan: a minimal checklist targeting only the changes made, enabling quick manual verification.

## What NOT to Do

- Add unrequested features
- Add error handling for impossible states
- Create abstractions for single uses
- Write speculative "future-proofing" code
- Commit debug prints or commented code
