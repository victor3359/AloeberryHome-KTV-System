# AloeberryHome KTV System

> Based on [PiKaraoke](https://github.com/vicwomg/pikaraoke) — enhanced with AI vocal separation, auto-generated karaoke lyrics, and a modern KTV experience.

A professional-grade home KTV system that transforms YouTube official MVs into fully-featured karaoke experiences with AI-powered vocal separation, real-time scrolling lyrics, and instant audio track switching.

## Key Features

- **AI Vocal Separation**: Download any official MV, Demucs (GPU) automatically separates vocals from instrumental
- **Auto Karaoke Lyrics**: Online-first lyrics (Musixmatch/Lrclib) + Whisper word timestamps, KTV two-line alternating layout with per-character color fill
- **Instant Audio Switching**: Toggle between Original/KTV (instrumental) modes with zero latency via HLS multi-audio
- **Real Pitch Shift**: SoundTouchJS AudioWorklet key change (+-12 semitones) without changing tempo
- **Microphone Scoring**: Real-time pitch detection (YIN algorithm) with visual feedback and accuracy-based scoring
- **Modern UI**: Dark neon glassmorphism theme, bottom 3-tab navigation (Songs/Queue/More), mobile-first touch design
- **Full Chinese UI**: All buttons, labels, notifications, and settings in Traditional Chinese
- **Song Library Management**: SQLite database with artist/title metadata, YouTube thumbnails, play counts, favorites
- **Song Recommendations**: AI-powered suggestions based on artist, language, and play history
- **Multi-Client Sync**: Multiple phones can connect via QR code, all synced in real-time via WebSocket
- **Fair Queue**: Nagle fair queuing algorithm ensures singers take turns
- **Session Management**: One-click session reset with KTV Wrapped summary screen

## System Requirements

- **OS**: Windows 10/11, macOS, Linux, Raspberry Pi
- **Python**: 3.10+
- **FFmpeg**: Required (with lib-rubberband recommended)
- **GPU** (optional): NVIDIA GPU with CUDA for faster Demucs processing
- **Browser**: Chrome/Edge recommended for full feature support

## Quick Install

### Prerequisites

```sh
# Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install FFmpeg
# Windows: winget install ffmpeg
# macOS: brew install ffmpeg
# Linux: sudo apt install ffmpeg
```

### Install

```sh
# Basic install (no AI features)
uv tool install pikaraoke

# Full install with AI (Demucs + Whisper + pitch scoring)
uv tool install "pikaraoke[ai]"
```

### Run

```sh
pikaraoke
```

Scan the QR code on the TV screen with your phone to start singing!

## Architecture

```
Download (YouTube)
  -> Demucs GPU (vocal/instrumental separation, ~30s)
  -> Whisper CPU (word-level lyrics transcription, ~60s)
  -> Online lyrics search (Musixmatch/Lrclib via syncedlyrics)
  -> Global LRC-MV offset correction (album vs MV timing)
  -> Word timeline alignment (online text + Whisper word timestamps)
  -> Hallucination filtering (credit lines, noise, repetitions)
  -> OpenCC s2twp (Simplified -> Taiwan Traditional Chinese)
  -> ASS karaoke subtitle (two-line KTV layout, per-char \kf fill)
  -> Reference pitch extraction (YIN algorithm)
  -> Auto song name normalization (regex_tidy)
  -> SQLite metadata database update
  -> Enqueue for playback

Playback:
  -> FFmpeg HLS multi-audio (original + instrumental tracks)
  -> HLS.js in browser with instant audio track switching
  -> SubtitlesOctopus renders two-line KTV subtitles (60fps, 4K)
  -> SoundTouchJS AudioWorklet pitch shift (no tempo change)
  -> Microphone pitch scoring (YIN algorithm, real-time feedback)
```

## AI Processing Pipeline

| Stage | Engine | Device | Time (typical) |
|-------|--------|--------|----------------|
| Vocal Separation | Demucs htdemucs | CUDA GPU | ~30s |
| Lyrics Transcription | faster-whisper / openai-whisper | CPU (subprocess) | ~60s |
| Online Lyrics Search | syncedlyrics (Musixmatch/Lrclib) | Network | ~2s |
| LRC-MV Offset Correction | Median text-similarity matching | CPU | \<1s |
| Word Timeline Alignment | Online text + Whisper word timestamps | CPU | \<1s |
| Hallucination Filtering | 49 keywords + 4 regex patterns | CPU | \<1s |
| Chinese Conversion | OpenCC (s2twp, Taiwan Traditional) | CPU | \<1s |
| ASS Subtitle Generation | Two-line KTV layout with \kf per-char fill | CPU | \<1s |
| Reference Pitch Extraction | YIN algorithm | CPU (subprocess) | ~30s |

## Configuration

### Settings (More -> Settings)

All settings are in Traditional Chinese. Key sections:

- **Session**: Fair queue, auto-DJ, song limit per person, delay between songs
- **Audio**: Volume, background music volume, equalize volume
- **Display**: TV theme (Classic/Party/Romantic/Neon), clock, QR code, overlays
- **Advanced**: A/V sync, buffer size, CDG pixel scaling

### GPU Setup (for AI features)

The system uses CUDA GPU for Demucs (vocal separation) and CPU for Whisper (lyrics). To enable GPU:

1. Install NVIDIA CUDA toolkit
2. Install with AI extras: `uv tool install "pikaraoke[ai]"`
3. Verify: system will log `Running demucs (device=cuda)...` on first download

## Development

```sh
git clone https://github.com/victor3359/AloeberryHome-KTV-System.git
cd AloeberryHome-KTV-System
uv run pikaraoke
```

### Running Tests

```sh
uv run pytest tests/unit/ -q
```

### Code Quality

```sh
uv run pre-commit run --config code_quality/.pre-commit-config.yaml --all-files
```

## Project Stats

- **120+ commits** across Round 2, Round 3, and lyrics optimization
- **750 tests** passing
- **60+ files** modified/created
- **10,000+ lines** of new code
- **CI**: 8/8 checks green (unit tests, code quality, smoke tests, Docker builds)

## Credits

- **Base Project**: [PiKaraoke](https://github.com/vicwomg/pikaraoke) by Vic Wong
- **AI Enhancement**: Claude Opus 4.6 (Anthropic)
- **Vocal Separation**: [Demucs](https://github.com/facebookresearch/demucs) by Meta Research
- **Speech Recognition**: [Whisper](https://github.com/openai/whisper) / [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- **Pitch Shift**: [SoundTouchJS](https://github.com/cutterbl/SoundTouchJS) AudioWorklet
- **Subtitle Rendering**: [SubtitlesOctopus](https://github.com/libass/JavascriptSubtitlesOctopus)
- **Traditional Chinese**: [OpenCC](https://github.com/BYVoid/OpenCC) (s2twp)
- **Online Lyrics**: [syncedlyrics](https://github.com/rtcq/syncedlyrics) (Musixmatch/Lrclib)

## License

See [LICENSE](LICENSE) for details.
