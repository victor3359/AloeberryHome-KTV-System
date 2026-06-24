# Splash Modularization Slice 4 — Extract scoring + pitch ES modules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `pitch-analyzer.js`, `pitch-meter.js`, and `score.js` from classic window-attaching scripts into native ES modules that `splash.js` imports, and move the `scoreReviews` phrase data off `window` into a scoring-owned module binding — eliminating the last cross-file global bridges in the scoring/pitch subsystem.

**Architecture:** `splash.js` is already an ES module (slices 1-3). Today it reaches the pitch classes (`PitchAnalyzer`/`PitchMeter`) and the score entrypoint (`startScore`) through implicit `window.*` globals, and `scoreReviews` is a bidirectional shared global between `splash.js` (init + socket update) and `score.js` (read + fetch-write). This slice makes those classes/functions explicit `export`s that splash `import`s, and relocates `scoreReviews` into `score.js` as a module-private `let` with a `setScoreReviews()` setter (the socket handler's only write). Library globals stay window-resolved: `launchFireworkShow` (fireworks.js, classic) is read bare by the new `score.js` module exactly as `Hls`/`io`/`$` are — do NOT import it.

**Tech Stack:** Native ES modules + import map (zero build step). Tests are Python string-assertion tests over the JS/template files (repo convention; no JS harness). Runtime behavior is covered by the manual TV checklist only.

## Global Constraints

- **No framework, no build step, zh-TW single-locale.** Behavior must be identical after each task (this is a structural refactor).
- **Import specifiers are absolute static paths** (the import map only aliases `core/` → `/static/core/`): `/static/js/pitch-analyzer.js`, `/static/js/pitch-meter.js`, `/static/score.js`. Absolute paths bypass the import map by design.
- **Library globals stay bare/window-resolved, NOT imported:** `launchFireworkShow` (fireworks.js), `Hls`, `io`, `$`, `PikaraokeConfig`, `Audio`. They are classic `function`/window-attached and resolve fine in module scope.
- **`splash` is direct-load-only** (blank_page=True; no `/splash` link). Do not introduce an SPA-routed load of splash.
- **Atomicity:** each task converts a file's writer→export AND every reader→import AND deletes the window assignment AND updates the boundary guard tests **together**, in one commit. There is no valid half-migrated intermediate (e.g. removing the classic `<script>` tag while a reader still expects the window global would throw at runtime).
- Quality gate before each commit: `uv run --no-sync pytest tests/ -q` green AND `uv run pre-commit run --config code_quality/.pre-commit-config.yaml --all-files` clean — drop unrelated `--all-files` formatter churn with `git checkout -- .`, keeping only this task's files.

---

### Task 1: Convert `pitch-analyzer.js` + `pitch-meter.js` to ES modules

Both are self-contained leaf classes (browser APIs only: `AudioContext`, canvas). They are symmetric and used only by `splash.js`, so converting both atomically avoids a half-migrated state (one import + one window-attach).

**Files:**
- Modify: `pikaraoke/static/js/pitch-analyzer.js` (class at line 11; window-attach block at lines 133-136)
- Modify: `pikaraoke/static/js/pitch-meter.js` (class at line 11; window-attach block at lines 144-146)
- Modify: `pikaraoke/static/js/splash.js` (add imports after line 2; `typeof` guard at line 428; usages at lines 640/645 are unchanged — the bare names now resolve to the imports)
- Modify: `pikaraoke/templates/splash.html` (remove the two classic `<script>` tags at lines 15-16)
- Modify: `tests/unit/test_splash_module_boundary.py` (rewrite `test_pitch_helpers_only_window_attach_their_classes` — the boundary is inverting)
- Test: `tests/unit/test_splash_pitch_modules.py` (new)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `pitch-analyzer.js` exports `class PitchAnalyzer`; `pitch-meter.js` exports `class PitchMeter`; `splash.js` imports both from their `/static/js/` paths. Task 2 does not depend on these.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_splash_pitch_modules.py`:

```python
import os
import re

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_PA = os.path.join(_PKG, "static", "js", "pitch-analyzer.js")
_PM = os.path.join(_PKG, "static", "js", "pitch-meter.js")
_SPLASH_JS = os.path.join(_PKG, "static", "js", "splash.js")
_SPLASH_HTML = os.path.join(_PKG, "templates", "splash.html")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_pitch_classes_are_exported_not_window_attached():
    pa, pm = _read(_PA), _read(_PM)
    assert re.search(r"^export class PitchAnalyzer\b", pa, re.M)
    assert re.search(r"^export class PitchMeter\b", pm, re.M)
    # The window leak is gone.
    assert "window.PitchAnalyzer" not in pa
    assert "window.PitchMeter" not in pm


def test_splash_imports_the_pitch_classes():
    js = _read(_SPLASH_JS)
    assert re.search(r'import \{[^}]*\bPitchAnalyzer\b[^}]*\} from "/static/js/pitch-analyzer\.js"', js)
    assert re.search(r'import \{[^}]*\bPitchMeter\b[^}]*\} from "/static/js/pitch-meter\.js"', js)


def test_splash_does_not_typeof_guard_an_imported_class():
    # With a static import PitchAnalyzer is always bound; the typeof "is the script loaded"
    # guard is dead and must be removed so it can't mask a missing import.
    js = _read(_SPLASH_JS)
    assert "typeof PitchAnalyzer" not in js


def test_splash_html_no_classic_pitch_script_tags():
    html = _read(_SPLASH_HTML)
    assert "js/pitch-analyzer.js" not in html
    assert "js/pitch-meter.js" not in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_splash_pitch_modules.py -v`
Expected: FAIL (classes still window-attached, splash has no imports, html still has the tags).

- [ ] **Step 3: Convert the two pitch classes to exports**

In `pikaraoke/static/js/pitch-analyzer.js`: change line 11 `class PitchAnalyzer {` to `export class PitchAnalyzer {`, and delete the trailing window-attach block (lines ~133-136):

```js
// Export for use in splash.js
if (typeof window !== "undefined") {
  window.PitchAnalyzer = PitchAnalyzer;
}
```

In `pikaraoke/static/js/pitch-meter.js`: change line 11 `class PitchMeter {` to `export class PitchMeter {`, and delete the trailing window-attach block (lines ~144-146):

```js
if (typeof window !== "undefined") {
  window.PitchMeter = PitchMeter;
}
```

- [ ] **Step 4: Import the classes in splash.js and drop the typeof guard**

In `pikaraoke/static/js/splash.js`, add after the existing bg-media import (line 2):

```js
import { PitchAnalyzer } from "/static/js/pitch-analyzer.js";
import { PitchMeter } from "/static/js/pitch-meter.js";
```

Change the feature guard at line 428 from:

```js
    if (!PikaraokeConfig.disableScore && typeof PitchAnalyzer !== "undefined") {
```

to:

```js
    if (!PikaraokeConfig.disableScore) {
```

(The `new PitchAnalyzer(...)` at line 640 and `new PitchMeter(...)` at line 645 are unchanged — the bare names now resolve to the imports.)

- [ ] **Step 5: Remove the classic pitch `<script>` tags**

In `pikaraoke/templates/splash.html`, delete lines 15-16:

```html
<script src="{{ url_for('static', filename='js/pitch-analyzer.js') }}"></script>
<script src="{{ url_for('static', filename='js/pitch-meter.js') }}"></script>
```

- [ ] **Step 6: Update the slice-2 boundary guard test (the boundary inverted)**

In `tests/unit/test_splash_module_boundary.py`, replace `test_pitch_helpers_only_window_attach_their_classes` with the inverse invariant:

```python
def test_pitch_helpers_export_their_classes_and_drop_the_window_leak():
    """Slice 4 converted the pitch helpers to ES modules: they now `export` their class and no
    longer attach it to window; splash imports them. Lock the new direction."""
    pa = _read(_PITCH_ANALYZER)
    pm = _read(_PITCH_METER)
    assert "export class PitchAnalyzer" in pa
    assert "export class PitchMeter" in pm
    assert "window.PitchAnalyzer" not in pa
    assert "window.PitchMeter" not in pm
```

- [ ] **Step 7: Run the new + updated tests, then the full suite**

Run: `uv run --no-sync pytest tests/unit/test_splash_pitch_modules.py tests/unit/test_splash_module_boundary.py -v` → all PASS.
Run: `uv run --no-sync pytest tests/ -q` → all green.
Run: `uv run pre-commit run --config code_quality/.pre-commit-config.yaml --all-files` → clean (drop unrelated churn with `git checkout -- .`, keeping only this task's files).

- [ ] **Step 8: Commit**

```bash
git add pikaraoke/static/js/pitch-analyzer.js pikaraoke/static/js/pitch-meter.js \
        pikaraoke/static/js/splash.js pikaraoke/templates/splash.html \
        tests/unit/test_splash_pitch_modules.py tests/unit/test_splash_module_boundary.py
git commit -m "refactor: convert pitch-analyzer/pitch-meter to ES modules imported by splash"
```

---

### Task 2: Convert `score.js` to an ES module that owns `scoreReviews`

This is the behavior-bearing core of the slice and carries the `scoreReviews` de-globalization trap. `scoreReviews` is bidirectional: `splash.js` initializes it (line 19) and updates it on the `score_phrases_update` socket event (line 783); `score.js` reads it (`getScoreData`, lines 7/9/11) and overwrites it from a fetch (`startScore`, line 63). Because an imported binding is read-only for the importer, ownership moves **into** `score.js`: a module-private `let scoreReviews` (seeded with splash's old default) plus an exported `setScoreReviews()` for the socket handler's write. `startScore` and `getScoreData` then read/write the module-private binding directly.

**Files:**
- Modify: `pikaraoke/static/score.js` (add the seeded `let scoreReviews` + `export function setScoreReviews`; `export` on `startScore`; `window.scoreReviews` → bare `scoreReviews` at lines 7/9/11/63)
- Modify: `pikaraoke/static/js/splash.js` (import `startScore, setScoreReviews`; delete the `window.scoreReviews = {...}` initializer at lines 19-23; rewire the socket handler at line 783)
- Modify: `pikaraoke/templates/splash.html` (remove the classic `score.js` `<script>` tag at line 273)
- Modify: `tests/unit/test_splash_module_boundary.py` (rewrite `test_no_classic_helper_reads_a_bare_splash_global` — score.js no longer reads a splash global)
- Modify: `tests/unit/test_splash_score_reviews_window.py` (slice-1 test that asserts `window.scoreReviews`; rewrite to assert score.js owns it)
- Test: `tests/unit/test_splash_scoring_module.py` (new)

**Interfaces:**
- Consumes: nothing from Task 1 (independent).
- Produces: `score.js` exports `async function startScore(staticPath, preCalculatedScore)` and `function setScoreReviews(next)`; owns `scoreReviews` privately. `splash.js` imports both. No further tasks depend on these.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_splash_scoring_module.py`:

```python
import os
import re

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_SCORE = os.path.join(_PKG, "static", "score.js")
_SPLASH_JS = os.path.join(_PKG, "static", "js", "splash.js")
_SPLASH_HTML = os.path.join(_PKG, "templates", "splash.html")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_score_js_exports_entrypoints():
    score = _read(_SCORE)
    assert re.search(r"^export async function startScore\b", score, re.M)
    assert re.search(r"^export function setScoreReviews\b", score, re.M)


def test_score_js_owns_score_reviews_off_window():
    score = _read(_SCORE)
    # scoreReviews is now a module-private binding, never on window.
    assert "window.scoreReviews" not in score
    assert re.search(r"^let scoreReviews\b", score, re.M)
    # getScoreData reads the bare module binding.
    assert "scoreReviews.low" in score and "scoreReviews.high" in score


def test_splash_imports_scoring_and_drops_window_score_reviews():
    js = _read(_SPLASH_JS)
    assert re.search(r'import \{[^}]*\bstartScore\b[^}]*\bsetScoreReviews\b[^}]*\} from "/static/score\.js"', js) \
        or re.search(r'import \{[^}]*\bsetScoreReviews\b[^}]*\bstartScore\b[^}]*\} from "/static/score\.js"', js)
    # splash no longer initializes or assigns window.scoreReviews; the socket handler uses the setter.
    assert "window.scoreReviews" not in js
    assert "setScoreReviews(phrases)" in js


def test_splash_html_no_classic_score_script_tag():
    html = _read(_SPLASH_HTML)
    assert "filename='score.js'" not in html and 'filename="score.js"' not in html
    # fireworks.js stays classic (launchFireworkShow is a kept window global).
    assert "fireworks.js" in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_splash_scoring_module.py -v`
Expected: FAIL (score.js still uses `window.scoreReviews` and has no exports; splash still owns the window init).

- [ ] **Step 3: Convert score.js — own `scoreReviews`, export the entrypoints**

In `pikaraoke/static/score.js`:

(a) Add at the very top of the file (relocating splash.js:19-23's default verbatim) and the setter:

```js
let scoreReviews = {
  low: ["Better luck next time!"],
  mid: ["Not bad!"],
  high: ["Great job!"],
};

export function setScoreReviews(next) {
  scoreReviews = next;
}
```

(b) In `getScoreData` (lines 7/9/11), change `window.scoreReviews.low/.mid/.high` to bare `scoreReviews.low/.mid/.high`.

(c) In `startScore` (line 60), add `export`: `export async function startScore(staticPath, preCalculatedScore) {`. At line 63 change `window.scoreReviews = await r.json();` to `scoreReviews = await r.json();`.

(d) Leave `getScoreValue`, `showFinalScoreWithAudio`, `rotateScore` module-private (unexported). They call `launchFireworkShow` bare — keep it bare (fireworks.js stays a classic window global; do NOT import it).

- [ ] **Step 4: Wire splash.js to the scoring module**

In `pikaraoke/static/js/splash.js`:

(a) Add after the pitch imports (Task 1) / bg-media import:

```js
import { startScore, setScoreReviews } from "/static/score.js";
```

(b) Delete the `window.scoreReviews` initializer at lines 19-23:

```js
window.scoreReviews = {
  low: ["Better luck next time!"],
  mid: ["Not bad!"],
  high: ["Great job!"],
};
```

(c) Rewire the socket handler at line 783 from:

```js
  socket.on("score_phrases_update", (phrases) => { window.scoreReviews = phrases; });
```

to:

```js
  socket.on("score_phrases_update", (phrases) => { setScoreReviews(phrases); });
```

(The two `startScore("/static/", ...)` calls at lines 167/170 are unchanged — the bare name now resolves to the import.)

- [ ] **Step 5: Remove the classic score.js `<script>` tag**

In `pikaraoke/templates/splash.html`, delete line 273 (keep `fireworks.js` at line 272 and `hls` at line 271):

```html
<script src="{{  url_for('static', filename='score.js') }}"></script>
```

- [ ] **Step 6: Update the slice-1/2 scoreReviews guard tests (boundary moved off window)**

In `tests/unit/test_splash_module_boundary.py`, rewrite `test_no_classic_helper_reads_a_bare_splash_global` — score.js is now a module that owns scoreReviews, so the cross-file split is gone:

```python
def test_no_classic_helper_reads_a_bare_splash_global():
    """After slice 4 the only classic helper still alongside the splash module is fireworks.js,
    which touches no splash-owned global. score.js is now an ES module that owns scoreReviews."""
    fireworks = _read(_FIREWORKS)
    assert re.search(r"(?<!window\.)\bscoreReviews\b", fireworks) is None
    score = _read(_SCORE)
    assert "window.scoreReviews" not in score  # owned as a module binding now
```

In `tests/unit/test_splash_score_reviews_window.py` (slice-1, asserts `window.scoreReviews`), rewrite it to lock the new ownership:

```python
def test_score_reviews_owned_by_scoring_module_not_window():
    score = _read(_SCORE)
    splash = _read(_SPLASH_JS)
    assert re.search(r"^let scoreReviews\b", score, re.M)
    assert "window.scoreReviews" not in score
    assert "window.scoreReviews" not in splash
```

(If `test_splash_score_reviews_window.py` has helper/import scaffolding, keep it; only the assertions about `window.scoreReviews` existence change. If a test there asserted score.js reads `window.scoreReviews`, it is now false and must be replaced as above.)

- [ ] **Step 7: Run the new + updated tests, then the full suite**

Run: `uv run --no-sync pytest tests/unit/test_splash_scoring_module.py tests/unit/test_splash_module_boundary.py tests/unit/test_splash_score_reviews_window.py -v` → all PASS.
Run: `uv run --no-sync pytest tests/ -q` → all green.
Run: `uv run pre-commit run --config code_quality/.pre-commit-config.yaml --all-files` → clean (drop unrelated churn with `git checkout -- .`).

- [ ] **Step 8: Commit**

```bash
git add pikaraoke/static/score.js pikaraoke/static/js/splash.js pikaraoke/templates/splash.html \
        tests/unit/test_splash_scoring_module.py tests/unit/test_splash_module_boundary.py \
        tests/unit/test_splash_score_reviews_window.py
git commit -m "refactor: convert score.js to an ES module that owns scoreReviews"
```

---

## Manual TV smoke checklist (after both tasks — no JS harness covers runtime)

Open `/splash` directly on the TV (or a browser) with DevTools console open:

1. **No console `ReferenceError`** on load (PitchAnalyzer/PitchMeter/startScore/setScoreReviews import failures would throw immediately and blank the page).
2. **Scoring path:** finish a song with scoring enabled → the score screen shows a number + a review phrase (exercises the module-private `scoreReviews` via `startScore`'s fetch) + fireworks (`launchFireworkShow` still resolves as a bare global from the score.js module) + applause.
3. **Mic pitch meter:** with scoring on and a mic, the pitch meter renders and updates during the song (exercises `new PitchAnalyzer` / `new PitchMeter` imports), and the final score is read from the meter.
4. **Phrase hot-update:** trigger a `score_phrases_update` socket event (admin reload of phrases) → the next score uses the new phrases (exercises `setScoreReviews`).
5. **Unaffected:** HLS playback, subtitles, background media, screensaver, permissions-confirm all still work; multi-screen master election unchanged.

What failure looks like: a blank splash + a console `Uncaught SyntaxError`/`ReferenceError` naming PitchAnalyzer/PitchMeter/startScore → an import path or export is wrong; score screen crashes / blank review text → `scoreReviews` ownership wiring is wrong.

---

## Self-Review

- **Spec coverage:** Implements analysis-doc slice 4 exactly — (1) `pitch-analyzer.js`/`pitch-meter.js` → ES modules with `window.PitchAnalyzer/PitchMeter` leakage replaced by imports (Task 1); (2) `score.js` → ES module with `scoreReviews` moved into a scoring-owned module binding + `setScoreReviews` setter, and `startScore` imported (Task 2). The known scoreReviews de-globalization trap is handled by making score.js the owner and giving the socket writer a setter (an exported `let` cannot be reassigned by the importer).
- **Placeholder scan:** none — every code edit shows the exact before/after; the only "move verbatim" is the scoreReviews default object, whose full content is given in Step 3a.
- **Type/name consistency:** `startScore(staticPath, preCalculatedScore)` and `setScoreReviews(next)` are named identically in score.js (exports), splash.js (imports + socket handler `setScoreReviews(phrases)`), and all three test files. `PitchAnalyzer`/`PitchMeter` import names match the `new` call sites and the boundary test.
- **Scope discipline:** library globals (`launchFireworkShow`, `Hls`, `io`, `$`, `Audio`, `PikaraokeConfig`) stay window-resolved — not imported. The splash-internal pitch INSTANCE state (`window._pitchAnalyzer`/`_pitchMeter`/`_referencePitch`/`_pitchShift*`) is deliberately OUT of scope here (it is splash-local runtime state, not a cross-file class leak) — leave it for a later session-state cleanup slice. Atomicity per task prevents any broken intermediate commit.
