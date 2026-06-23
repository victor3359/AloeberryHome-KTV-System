# Splash Modularization Slice 3 — Extract bg-media Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the background-music/background-video concern out of `splash.js` into a self-contained ES module `modules/bg-media.js`, establishing the dependency-injection pattern for splash-owned state — behavior identical.

**Architecture:** `bg-media.js` owns its own state (`bg_playlist`, `bgMediaResumeTimeout`, `bgMediaResumeDelay`, `hasBgVideo`) and exports the 6 functions splash still calls (`getBackgroundMusicPlayer`, `playBGMusic`, `playBGVideo`, `shouldBackgroundMediaPlay`, `updateBackgroundMediaState`, `setupBackgroundMusicPlayer`) plus an `initBgMedia(deps)`. It imports nothing back from splash — the three splash-owned things it reads (`nowPlaying`, `autoplayConfirmed`, and the player-core helper `isMediaPlaying`) are injected via `initBgMedia`, keeping the dependency direction one-way (splash → bg-media) and avoiding a circular import. Full slice roadmap and verified facts: `docs/superpowers/specs/2026-06-24-splash-modularization-analysis.md` (slice 3).

**Tech Stack:** Native ES modules (splash.js is already `type="module"` from slice 1; the boundary-guard tests from slice 2 protect this work). Python string-assertion tests; no JS harness.

## Global Constraints

- Backend untouched. Behavior must stay IDENTICAL (background music/video autoplay, resume-after-song gating, the permissions-modal confirm path, the bg_video/bg_music/volume preference toggles, the screensaver's bg-video handoff).
- This is an **atomic** extraction: the module is created AND splash is rewired in one commit. A half-state where splash both defines and imports the same name is a SyntaxError, so there is no valid intermediate — it is one task.
- bg-media.js must import nothing from splash.js (no circular import). The three injected accessors are the only channel for splash state.
- Keep library/host globals (`$`/jQuery, `PikaraokeConfig`, `document`, `setTimeout`/`clearTimeout`, `console`) as bare names — they resolve via `window` in module scope (verified safe in slices 1-2). Do NOT import them.
- Do NOT change behavior of, or touch, any non-bg-media concern (player-core `isMediaPlaying`/`getVideoPlayer` stay in splash; `PREFERENCE_EFFECTS`, `toggleBGMedia`, `setupScreensaver`, `handleConfirmation`, `handleNowPlayingUpdate` stay in splash and now call the imported bg-media functions).
- New module path: `pikaraoke/static/js/modules/bg-media.js`, imported via the absolute path `/static/js/modules/bg-media.js` (the import map only aliases `core/`; absolute paths bypass it — same pattern as the screensaver import).
- Code style: keep the moved function bodies byte-identical except the three injected-accessor substitutions. No emoji; delete (not comment out) the originals.
- Quality gate: `uv run --no-sync pytest tests/ -q` green AND `uv run pre-commit run --config code_quality/.pre-commit-config.yaml --all-files` clean (drop unrelated `--all-files` formatter churn with `git checkout -- .`, keeping only this slice's files).

---

### Task 1: Extract bg-media into modules/bg-media.js

**Files:**
- Create: `pikaraoke/static/js/modules/bg-media.js`
- Modify: `pikaraoke/static/js/splash.js` (add import + `initBgMedia` call; delete the 8 function defs + 4 state vars that moved)
- Test: `tests/unit/test_splash_bg_media_module.py`

**Interfaces:**
- `bg-media.js` exports: `initBgMedia(deps)` where `deps = { getNowPlaying, getAutoplayConfirmed, isMediaPlaying }`; and `getBackgroundMusicPlayer`, `playBGMusic`, `playBGVideo`, `shouldBackgroundMediaPlay`, `updateBackgroundMediaState`, `setupBackgroundMusicPlayer`.
- `getNowPlaying()` returns the splash `nowPlaying` object; `getAutoplayConfirmed()` returns the splash `autoplayConfirmed` boolean; `isMediaPlaying(mediaEl)` is the splash player-core helper.
- splash.js calls `initBgMedia({ getNowPlaying: () => nowPlaying, getAutoplayConfirmed: () => autoplayConfirmed, isMediaPlaying })` once, before any bg-media function runs.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_splash_bg_media_module.py`:

```python
import os
import re

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_BGMEDIA = os.path.join(_PKG, "static", "js", "modules", "bg-media.js")
_SPLASH = os.path.join(_PKG, "static", "js", "splash.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_bg_media_module_exists_and_exports_api():
    bg = _read(_BGMEDIA)
    assert "export function initBgMedia(" in bg
    for name in (
        "getBackgroundMusicPlayer",
        "playBGMusic",
        "playBGVideo",
        "shouldBackgroundMediaPlay",
        "updateBackgroundMediaState",
        "setupBackgroundMusicPlayer",
    ):
        assert re.search(rf"export const {name}\b", bg), f"bg-media.js must export {name}"


def test_bg_media_uses_injected_accessors_not_splash_state():
    """bg-media must read splash state only through injected accessors, never as bare globals
    (it is a module that imports nothing from splash)."""
    bg = _read(_BGMEDIA)
    assert "getAutoplayConfirmed()" in bg
    assert "getNowPlaying()" in bg
    # No bare splash-owned identifiers leaked into the module.
    assert re.search(r"(?<!\.)\bautoplayConfirmed\b", bg) is None
    assert re.search(r"(?<![.\w])\bnowPlaying\b", bg) is None
    # bg-media imports nothing back from splash (no circular import).
    assert "splash.js" not in bg


def test_splash_imports_bg_media_and_inits_it():
    splash = _read(_SPLASH)
    assert (
        'import {' in splash
        and 'from "/static/js/modules/bg-media.js";' in splash
    )
    # The injected accessors are wired exactly once.
    assert "initBgMedia({" in splash
    assert "getNowPlaying: () => nowPlaying" in splash
    assert "getAutoplayConfirmed: () => autoplayConfirmed" in splash
    assert "isMediaPlaying" in splash  # passed through as the third dep


def test_splash_no_longer_defines_bg_media_functions_or_state():
    """The moved definitions must be gone from splash (else module import collides with a local
    declaration of the same name -> SyntaxError)."""
    splash = _read(_SPLASH)
    for decl in (
        "const playBGMusic =",
        "const playBGVideo =",
        "const shouldBackgroundMediaPlay =",
        "const updateBackgroundMediaState =",
        "const setupBackgroundMusicPlayer =",
        "const getBackgroundMusicPlayer =",
        "const getBackgroundVideoPlayer =",
        "const getNextBgMusicSong =",
        "let bg_playlist =",
        "let bgMediaResumeTimeout =",
        "const bgMediaResumeDelay =",
        "const hasBgVideo =",
    ):
        assert decl not in splash, f"splash.js must no longer define `{decl}` (moved to bg-media.js)"
    # player-core helpers that must STAY in splash:
    assert "const isMediaPlaying =" in splash
    assert "const getVideoPlayer =" in splash
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_splash_bg_media_module.py -v`
Expected: FAIL (module file does not exist; splash still defines the functions).

- [ ] **Step 3: Create `pikaraoke/static/js/modules/bg-media.js`**

Create the file with exactly this content (the moved bodies are byte-identical except the three injected-accessor substitutions: `autoplayConfirmed` → `getAutoplayConfirmed()`, `nowPlaying` → `getNowPlaying()`; `isMediaPlaying(...)` call sites are unchanged because the injected dep is named `isMediaPlaying`):

```javascript
// ES module: background music + video playback for the splash (TV) page.
// Extracted from splash.js. Imports nothing back from splash; the splash-owned state it needs
// (now-playing, autoplay-confirmed) and the player-core helper isMediaPlaying are injected via
// initBgMedia() so the dependency direction stays one-way (splash -> bg-media).

// Injected accessors (set by initBgMedia at boot; defaults are safe no-ops).
let getNowPlaying = () => ({});
let getAutoplayConfirmed = () => false;
let isMediaPlaying = () => false;

export function initBgMedia(deps) {
  getNowPlaying = deps.getNowPlaying;
  getAutoplayConfirmed = deps.getAutoplayConfirmed;
  isMediaPlaying = deps.isMediaPlaying;
}

// Module-private state.
const bgMediaResumeDelay = 2000;
const hasBgVideo = PikaraokeConfig.hasBgVideo;
let bg_playlist = [];
let bgMediaResumeTimeout = null;

export const getBackgroundMusicPlayer = () => document.getElementById('background-music');
const getBackgroundVideoPlayer = () => document.getElementById('bg-video');

const getNextBgMusicSong = () => {
  let currentSong = getBackgroundMusicPlayer().getAttribute('src');
  let nextSong = bg_playlist[0];
  if (currentSong) {
    let currentIndex = bg_playlist.indexOf(currentSong);
    if (currentIndex >= 0 && currentIndex < bg_playlist.length - 1) {
      nextSong = bg_playlist[currentIndex + 1];
    }
  }
  return nextSong;
}

export const playBGMusic = async (play) => {
  const audio = getBackgroundMusicPlayer();
  if (play) {
    if (PikaraokeConfig.disableBgMusic) return;
    if (!getAutoplayConfirmed()) return;
    if (bg_playlist.length === 0) return;

    if (!audio.getAttribute('src')) audio.setAttribute('src', getNextBgMusicSong());

    if (isMediaPlaying(audio)) return;
    audio.volume = 0;
    if (audio.readyState <= 2) await audio.load();
    await audio.play().catch(e => console.log("Autoplay blocked (music)"));
    $(audio).animate({ volume: PikaraokeConfig.bgMusicVolume }, 2000);
  } else {
    if (audio) {
      $(audio).animate({ volume: 0 }, 2000, () => audio.pause());
    }
  }
}

export const playBGVideo = async (play) => {
  const bgVideo = getBackgroundVideoPlayer();
  const bgVideoContainer = $('#bg-video-container');

  if (play) {
    if (PikaraokeConfig.disableBgVideo) return;
    if (!getAutoplayConfirmed()) return;

    if (isMediaPlaying(bgVideo)) return;
    $("#bg-video").attr("src", "/stream/bg_video");
    if (bgVideo.readyState <= 2) await bgVideo.load();
    bgVideo.play().catch(() => console.log("Autoplay blocked (video)"));
    bgVideoContainer.fadeIn(2000);
  } else {
    if (bgVideo && isMediaPlaying(bgVideo)) {
      bgVideo.pause();
      bgVideoContainer.fadeOut(2000);
    }
  }
}

export const shouldBackgroundMediaPlay = () => {
  return getAutoplayConfirmed() &&
    !getNowPlaying().now_playing &&
    !getNowPlaying().up_next;
};

export const updateBackgroundMediaState = (immediate = false) => {
  // Clear any pending resume
  if (bgMediaResumeTimeout) {
    clearTimeout(bgMediaResumeTimeout);
    bgMediaResumeTimeout = null;
  }

  if (shouldBackgroundMediaPlay()) {
    if (immediate) {
      playBGMusic(true);
      if (hasBgVideo) playBGVideo(true);
    } else {
      bgMediaResumeTimeout = setTimeout(() => {
        bgMediaResumeTimeout = null;
        if (shouldBackgroundMediaPlay()) {
          playBGMusic(true);
          if (hasBgVideo) playBGVideo(true);
        }
      }, bgMediaResumeDelay);
    }
  } else {
    playBGMusic(false);
    playBGVideo(false);
  }
};

export const setupBackgroundMusicPlayer = () => {
  $.get("/bg_playlist", function (data) {
    if (data) bg_playlist = data;
  });
  const bgMusic = getBackgroundMusicPlayer();
  bgMusic.addEventListener("ended", async () => {
    bgMusic.setAttribute('src', getNextBgMusicSong());
    await bgMusic.load();
    await bgMusic.play();
  });
}
```

- [ ] **Step 4: Add the import + init to splash.js**

In `pikaraoke/static/js/splash.js`, add a second import line immediately after the existing screensaver import (currently line 1):

```javascript
import { getBackgroundMusicPlayer, playBGMusic, playBGVideo, shouldBackgroundMediaPlay, updateBackgroundMediaState, setupBackgroundMusicPlayer, initBgMedia } from "/static/js/modules/bg-media.js";
```

Then, immediately AFTER the `isMediaPlaying` definition (the `const isMediaPlaying = (media) => !!( ... );` block), add the init call so bg-media is wired before any bg-media function can run (`isMediaPlaying`, `nowPlaying`, and `autoplayConfirmed` are all declared above this point):

```javascript

// Wire bg-media's injected accessors before any bg-media function (setupScreensaver,
// setupBackgroundMusicPlayer, the now_playing handler) can run.
initBgMedia({
  getNowPlaying: () => nowPlaying,
  getAutoplayConfirmed: () => autoplayConfirmed,
  isMediaPlaying,
});
```

- [ ] **Step 5: Delete the moved definitions from splash.js**

Remove these from `splash.js` (they now live in bg-media.js). Delete:

1. The four state declarations: `const bgMediaResumeDelay = 2000;`, `const hasBgVideo = PikaraokeConfig.hasBgVideo;`, `let bg_playlist = [];`, `let bgMediaResumeTimeout = null;`.
2. The two getter lines `const getBackgroundMusicPlayer = () => document.getElementById('background-music');` and `const getBackgroundVideoPlayer = () => document.getElementById('bg-video');` — but KEEP the line between/after them: `const getVideoPlayer = () => $("#video")[0]` (player-core, stays).
3. The contiguous block of bg-media functions: `getNextBgMusicSong`, `playBGMusic`, `playBGVideo`, `shouldBackgroundMediaPlay`, and `updateBackgroundMediaState` (from `const getNextBgMusicSong = () => {` through the closing `};` of `updateBackgroundMediaState`).
4. The `setupBackgroundMusicPlayer` block (`const setupBackgroundMusicPlayer = () => { ... }`).

Do NOT delete `isMediaPlaying`, `getVideoPlayer`, or any caller (`handleConfirmation`, `setupScreensaver`, `handleNowPlayingUpdate`, `toggleBGMedia`, `PREFERENCE_EFFECTS`, the boot `setupBackgroundMusicPlayer()` call) — those stay and now resolve the bg-media names via the import.

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run --no-sync pytest tests/unit/test_splash_bg_media_module.py -v`
Expected: PASS (4 tests). If `test_splash_no_longer_defines_bg_media_functions_or_state` still fails, a deletion was missed; if `test_bg_media_uses_injected_accessors_not_splash_state` fails, a bare `nowPlaying`/`autoplayConfirmed` leaked into the module.

- [ ] **Step 7: Run the full suite + lint gate**

Run: `uv run --no-sync pytest tests/ -q` → all green.
Run: `uv run pre-commit run --config code_quality/.pre-commit-config.yaml --all-files` → clean (drop unrelated churn with `git checkout -- .`, keeping only `modules/bg-media.js`, `splash.js`, and the new test).

**Manual test checklist (TV page — load splash directly):**
- DevTools console: no `ReferenceError` (`playBGMusic`, `updateBackgroundMediaState`, `getBackgroundMusicPlayer`, etc. all resolve via the import; `nowPlaying`/`autoplayConfirmed` resolve via the injected getters).
- Idle the page with nothing playing → background music starts (if a `/bg_playlist` exists) and, if `hasBgVideo`, the background video plays; click the permissions-modal confirm first if autoplay is gated.
- Start a song → background music/video stop; finish the song → after ~2s (`bgMediaResumeDelay`) background media resumes (the `updateBackgroundMediaState` non-immediate path).
- In the remote preferences, toggle 背景音樂/背景影片 off and on → `disable_bg_music`/`disable_bg_video` effects still start/stop the right media; change 背景音樂音量 → volume animates if music is playing (`bg_music_volume` → `getBackgroundMusicPlayer()`).
- Screensaver: idle past timeout → bg-video handoff still works (`setupScreensaver` calls `playBGVideo(false)` then the screensaver, and `updateBackgroundMediaState(true)` on wake).

- [ ] **Step 8: Commit**

```bash
git add pikaraoke/static/js/modules/bg-media.js pikaraoke/static/js/splash.js tests/unit/test_splash_bg_media_module.py
git commit -m "refactor: extract bg-media from splash.js into modules/bg-media.js"
```

---

## Self-Review

- **Spec coverage:** Implements analysis-doc slice 3 — extract bg-media with injected `nowPlaying`/`autoplayConfirmed` getters; this plan also injects `isMediaPlaying` (a player-core helper bg-media calls) to avoid a circular import, which the analysis's "inject accessors" intent covers. The boundary guards from slice 2 (`test_splash_module_boundary.py`) continue to pass (no new inline handlers; no new bare cross-file global).
- **Placeholder scan:** none — the full module is given and the deletions are explicit.
- **Type/name consistency:** the 6 exported names match between the module's `export const`, splash's `import { ... }`, and the test. `initBgMedia` deps `{ getNowPlaying, getAutoplayConfirmed, isMediaPlaying }` match the splash call site `{ getNowPlaying: () => nowPlaying, getAutoplayConfirmed: () => autoplayConfirmed, isMediaPlaying }`.
- **Behavior parity / ordering:** injected getters close over splash's live `let nowPlaying`/`autoplayConfirmed`, so they see updates (e.g. `handleConfirmation` sets `autoplayConfirmed = true` then calls `updateBackgroundMediaState`; the getter returns the new value). `initBgMedia` runs at module-execution time right after the accessors' sources are declared, before the boot block and before any socket-driven call. `hasBgVideo`/`PikaraokeConfig` read at module load resolve via the classic inline config script that runs before deferred modules. The single behavior risk is a missed deletion or a leaked bare global — both are covered by the test's no-redefine + no-bare-accessor assertions, and behavior is covered by the manual checklist.
- **Atomicity:** one task — the module-create and splash-rewire cannot be separate commits (duplicate name declaration would be a SyntaxError).
