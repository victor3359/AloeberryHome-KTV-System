# splash.js Modularization — Analysis & Slice Plan (AloeberryHome KTV System)

- **Date:** 2026-06-24
- **Status:** Analysis complete (multi-agent Understand workflow + adversarial critique + controller verification). Awaiting go/no-go on slice 1.
- **Source of truth for module targets:** `docs/superpowers/specs/2026-06-22-ktv-frontend-refactor-design.md` §5.2.
- **Method:** 5 parallel facet-mappers (globals/state, socket handlers, cross-file coupling, function→module map, load lifecycle) → synthesis → adversarial critic. Critical findings independently verified by grep before recording here.

## 1. Why this is the highest-risk item

`splash.js` is a **1045-line classic `<script>`** (the big-screen TV player). It carries ~30 top-level bindings, ~25 socket handlers aggregated in one `setupSocketEvents` god-function (783-975), and a 174-line `handleNowPlayingUpdate` god-handler (344-517) that drives nearly every concern. It reaches helper files (`score.js`, `fireworks.js`, `pitch-analyzer.js`, `pitch-meter.js`, `screensaver.js`) through **implicit shared globals**, not imports.

## 2. Risk-ranked decomposition (coupling = extraction difficulty)

| Module | Coupling | Notes |
|---|---|---|
| **screensaver** (cross-file edge) | low | `screensaver.js` is fully self-contained (DOM + rAF, zero splash symbols). The splash↔screensaver edge is one-directional (splash calls `startScreensaver`/`stopScreensaver`). Cleanest seam. |
| **bg-media** | low | 7 focused fns; only inward reads are `nowPlaying` + `autoplayConfirmed` (inject as getters). |
| **session-ui** | medium | Pure formatters + isolated timers/toasts are clean leaves; the now-playing/up-next DOM block is embedded in `handleNowPlayingUpdate`. |
| **scoring** | medium | `scoreReviews` is a **bidirectional shared global** with `score.js` (see §4). `PitchAnalyzer`/`PitchMeter` reach splash via `window.*` leakage. |
| **pitch-shift** | medium | `_pitchShiftCtx`/`_pitchShiftNode` managed by THREE scattered lifecycle sites (endSong:139-146, handleNowPlayingUpdate:432-439, pitch_shift handler:893-907) — consolidation is the value and the risk. |
| **subtitles** | high | SubtitlesOctopus init embedded inside `handleNowPlayingUpdate`; coupled to `uiScale` + the `audio_mode_switch` micro-seek that repairs sync. |
| **audio-pipeline** | high | HLS block embedded in `handleNowPlayingUpdate`; `hlsInstance`/`audioTrackMap` lifecycle has no ownership boundary. |
| **player-core** | high | `handleNowPlayingUpdate` + `endSong` are the dominant entanglement; `nowPlaying` is a central blob read by 4+ modules. Keystone. |
| **sync** | high | `setupSocketEvents` god-handler aggregates ALL wiring; `socket` mutable + reassigned in `handleSocketRecovery`; handlers not idempotent; uses bare `io()` not `window.getSocket()`. |
| **config/prefs** | high | `PREFERENCE_EFFECTS` is the central config→module fan-out (11 keys, 7 modules); must be assembled LAST as a thin registry importing effect callbacks. |

## 3. Recommended slice order (lowest-risk first)

1. **Slice 1 — Establish the ES-module boundary (ATOMIC, see §4 for the mandatory bundled fix).** Convert `splash.js` to `<script type="module">`, make `screensaver.js` exports the first real import, AND de-globalize `scoreReviews` in the same atomic change. Add the SPA-invariant test + multi-screen manual check.
2. **Slice 2 — Harden the module-conversion surface.** Grep `splash.html` for all inline `on*=` handlers; assign every HTML-referenced splash fn to `window`; pin each with a string-assertion test. Remove dead `// depends on upstream` comments.
3. **Slice 3 — Extract `bg-media`** into `modules/bg-media.js` (inject `nowPlaying`/`autoplayConfirmed` getters). First internal-logic module; establishes the dependency-injection pattern.
4. **Slice 4 — Extract `scoring`** + convert `pitch-analyzer.js`/`pitch-meter.js`/`score.js` to ES modules; replace `window.PitchAnalyzer/PitchMeter` leakage + bare reads (splash:500/724/729) with imports; move `scoreReviews` into a shared module binding owned by scoring.
5. **Slice 5 — Extract `session-ui` leaves** (formatters, timers, toasts, `session_summary`, overlay menus). Move `cursorVisible`/`menuButtonVisible` to a shared session-state binding.
6. **Slice 6 — Extract `config/prefs` leaves**; rebuild `PREFERENCE_EFFECTS` as a thin registry importing effect callbacks from already-extracted modules. `uiScale` via exported getter.
7. **Slice 7 — Split `handleNowPlayingUpdate`**: carve out `subtitles` (Octopus block 386-420) and `audio-pipeline` (HLS 452-476 + `audio_mode_switch`), introducing a `nowPlaying` store/getter all consumers import.
8. **Slice 8 — Extract `pitch-shift`**, consolidating the three AudioContext lifecycle sites behind one owner.
9. **Slice 9 — Extract `player-core` + `sync` LAST, together.** Align socket to `window.getSocket()`; fix the stale-closure-on-reassignment bug; make handlers idempotent (`.off()` before `.on()`).

## 4. Slice 1 — the corrected, atomic definition

The naive "just add `type=module` + screensaver import" is **UNSAFE**. The adversarial critic found, and grep confirmed, a slice-blocking break:

> **CRITICAL:** `splash.js` top-level `let scoreReviews` (line 21) silently becomes module-scoped when splash becomes a module. `score.js` (still classic) reads it bare at `score.js:7/9/11` (`scoreReviews.low/mid/high`) AND writes it at `score.js:63` (`scoreReviews = await r.json()`); splash also writes it at `splash.js:867`. After conversion these bare references throw `ReferenceError` the instant a song ends with scoring → the score screen crashes. The "behavior identical" constraint is violated.

**Verified facts (grep, 2026-06-24):**
- `score.js` reads/writes bare `scoreReviews` (only helper→splash global crossing; `fireworks.js`/`pitch-*.js` read no splash globals).
- Inline handlers in `splash.html`: exactly two, both `onClick="handleConfirmation()"` (lines 204 anchor, 211 button) — one `window.handleConfirmation =` covers both.
- No template links to `/splash` (splash is reached only by direct browser nav: `blank_page=True`, auto-launch) — SPA-module risk is future-regression only.
- Bare cross-file globals splash READS (`Hls`, `SubtitlesOctopus`, `PitchAnalyzer`, `PitchMeter`, `startScore`, `launchFireworkShow`, `io`, `$`, `Cookies`, `PikaraokeConfig`, `getSemitonesLabel` @base.html:49, `setUserCookie` @base.html:66) are all classic `function`-statements / window-attached → still resolve in module scope. Keep them as bare/window globals; do NOT import library globals.

**Slice 1 atomic change set:**
1. `pikaraoke/static/screensaver.js`: add `export` to `startScreensaver` (line 51) and `stopScreensaver` (line 56); add a top comment marking it import-only (ES module). Nothing else moves.
2. `pikaraoke/static/js/splash.js`: add `import { startScreensaver, stopScreensaver } from "/static/screensaver.js";` at top; add `window.handleConfirmation = handleConfirmation;`; **de-globalize scoreReviews**: write `window.scoreReviews` at init (line 21 area) and on the `score_phrases_update` handler (line 867); update/remove the splash:329/335 dependency comments.
3. `pikaraoke/static/score.js`: read/write `window.scoreReviews` instead of bare `scoreReviews` (lines 7/9/11 reads, line 63 write).
4. `pikaraoke/templates/splash.html`: change the `splash.js` tag (line 35) to `type="module"`; REMOVE the classic `screensaver.js` body tag (line 272).

**Tests (Python string-assertion, repo convention):** assert `type="module"` on splash.js tag; no classic screensaver.js tag; `import { startScreensaver, stopScreensaver }` present; `window.handleConfirmation =` present; `screensaver.js` has both `export function`; `score.js` reads `window.scoreReviews` (no bare `scoreReviews.` read); splash writes `window.scoreReviews`; inline `on*=` count in splash.html == 2 (both handleConfirmation); **invariant test**: no template contains an SPA-eligible link to `/splash`.

**Manual checklist (TV page, no JS harness):** no console `ReferenceError` (startScreensaver/stopScreensaver/handleConfirmation/scoreReviews); idle → DVD-bounce screensaver starts; move mouse / start song → stops; click permissions confirm (both the anchor and the button) → bg media + now-playing load; **scoring path**: finish a song with scoring on → score screen + review text render (exercises `window.scoreReviews`); HLS playback, subtitles, pitch unaffected; **multi-screen**: load two splash screens → exactly one master, `register_splash` not double-emitted (the defer-timing risk).

## 5. Cross-cutting risks (apply to every slice)

1. **Module scope drops auto-window-binding** → inline `on*=` HTML handlers break. Mitigation: assign every HTML-referenced fn to `window` in the same commit; grep + pin with tests.
2. **`socket` mutable + reassigned** (handleSocketRecovery:984) → stale-closure latent bug. Do NOT "fix" as a side effect; address deliberately in the sync slice via `window.getSocket()`.
3. **`setupSocketEvents` not idempotent** (no `.off()` before `.on()`); relies on a fresh `io()` per load. Keep the fresh-socket invariant until the sync slice.
4. **Shared mutable state across module boundaries** (`nowPlaying`, `autoplayConfirmed`, `scoreReviews`, `idleTime`/`screensaverTimeoutSeconds`/`uiScale`). Pass accessor getters, not snapshots; `export let` copies break live reads. Use store/getter modules (or the existing `core/nowPlayingStore.js`).
5. **Implicit `window.*` bridges are easy to half-migrate** (`window.PitchAnalyzer/PitchMeter`, `window.audioTrackMap`, `window._currentSubtitleUrl`, `window._pitchShift*`). Migrate each bridge atomically (writer→export, reader→import, delete the window assignment together) + assert the leak is gone.
6. **Load-order/timing**: classic body helpers (hls/fireworks/score) run before the deferred module. Keep all helper-global access lazy (inside callbacks). When converting fireworks/score to modules, import them and remove the classic tags in the same commit.
7. **SPA-module incompatibility (future-regression):** if anyone adds an in-app `<a href="/splash">`, the SPA loader re-injects splash.js as a classic `<script>` and the `import` throws SyntaxError → blank TV. Guard with an invariant test; splash MUST stay direct-load-only once it is a module.
