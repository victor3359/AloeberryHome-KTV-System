# Splash Modularization Slice 1 — ES-module boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the ES-module boundary for the splash (TV player) page — convert `splash.js` to `<script type="module">` with `screensaver.js` as its first real `import` — without any behavior change, by first neutralizing the one cross-file global (`scoreReviews`) that module scope would otherwise silently break.

**Architecture:** Two sequenced, each-independently-behavior-preserving tasks. Task 1 moves the `scoreReviews` shared global onto `window` (works identically in classic scope, so the intermediate state is fully functional). Task 2 then converts `splash.js` to a module — now safe, because the de-globalization trap is already gone. Full background, verified facts, and the 9-slice roadmap are in `docs/superpowers/specs/2026-06-24-splash-modularization-analysis.md`.

**Tech Stack:** Flask/Jinja templates, classic + ES-module `<script>`s, native import map (`base.html` already maps `core/` → `/static/core/`). Frontend tests are Python string-assertion tests over template/JS files (no JS harness, zero build) — runtime behavior is the per-task manual checklist.

## Global Constraints

- Backend untouched. No new routes, no contract changes. zh-TW single locale. No framework, no build step.
- **Behavior must stay identical.** Both tasks are behavior-preserving on their own; the intermediate commit (after Task 1) must be fully working.
- The splash page is reached **only by direct browser navigation** (no template links to `/splash`; `blank_page=True`). Once `splash.js` is a module it **must stay direct-load-only** — an SPA-routed load would re-inject it as a classic `<script>` and the `import` would throw. Task 2 adds an invariant test guarding this.
- Keep all helper/library globals (`Hls`, `SubtitlesOctopus`, `PitchAnalyzer`, `PitchMeter`, `startScore`, `launchFireworkShow`, `io`, `$`, `Cookies`, `PikaraokeConfig`, `getSemitonesLabel`, `setUserCookie`) as bare/`window`-resolved names — they are classic `function`-statements / window-attached and still resolve in module scope. Do NOT import library globals.
- Do NOT "fix" unrelated latent issues (the `socket` stale-closure, non-idempotent socket handlers, bare `io()` vs `getSocket()`) — those belong to the final sync slice.
- Code style: match surrounding file; no emoji; delete (not comment out) dead code.
- Quality gate before done: `uv run --no-sync pytest tests/ -q` green AND `uv run pre-commit run --config code_quality/.pre-commit-config.yaml --all-files` clean. (After a slice, run `git checkout -- .` to drop any unrelated `--all-files` formatter churn before finishing — see the analysis doc / memory.)

---

### Task 1: Move `scoreReviews` onto `window` (de-globalize, splash stays classic)

**Problem:** `splash.js` owns `let scoreReviews` (top-level) and `score.js` reads/writes it as a bare global. Today both are classic scripts sharing the global scope, so this works. When `splash.js` becomes a module (Task 2) its `let scoreReviews` becomes module-scoped and `score.js` (still classic) throws `ReferenceError`. Moving the binding to `window.scoreReviews` now makes it survive the module conversion — and is behavior-identical while both files are still classic.

**Files:**
- Modify: `pikaraoke/static/js/splash.js` (line 21 init block; line 867 `score_phrases_update` handler)
- Modify: `pikaraoke/static/score.js` (lines 7, 9, 11 reads; line 63 write)
- Test: `tests/unit/test_splash_score_reviews_window.py`

**Interfaces:**
- Produces: the single source of truth for score phrases is now `window.scoreReviews` (object with `.low`/`.mid`/`.high` arrays). Task 2 relies on this so the module conversion doesn't break `score.js`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_splash_score_reviews_window.py`:

```python
import os
import re

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_SPLASH = os.path.join(_PKG, "static", "js", "splash.js")
_SCORE = os.path.join(_PKG, "static", "score.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_score_reviews_is_window_scoped():
    """splash.js owns the score-phrases object and score.js reads/writes it. It must live on
    window so it survives splash.js becoming an ES module (module scope would otherwise trap a
    top-level `let` and break score.js's bare reads)."""
    splash = _read(_SPLASH)
    score = _read(_SCORE)
    # splash writes window.scoreReviews at init and on the socket update.
    assert "window.scoreReviews = {" in splash
    assert "window.scoreReviews = phrases" in splash
    # score.js reads/writes window.scoreReviews.
    assert "window.scoreReviews.low" in score
    assert "window.scoreReviews = await r.json()" in score
    # No bare (non-window) scoreReviews reference remains in either file.
    assert re.search(r"(?<!window\.)\bscoreReviews\b", splash) is None
    assert re.search(r"(?<!window\.)\bscoreReviews\b", score) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_splash_score_reviews_window.py -v`
Expected: FAIL (`window.scoreReviews` strings absent; bare `scoreReviews` still present).

- [ ] **Step 3: Move the splash.js binding onto window**

In `pikaraoke/static/js/splash.js`, replace the init block (line 21):

```javascript
let scoreReviews = {
  low: ["Better luck next time!"],
  mid: ["Not bad!"],
  high: ["Great job!"],
};
```

with:

```javascript
window.scoreReviews = {
  low: ["Better luck next time!"],
  mid: ["Not bad!"],
  high: ["Great job!"],
};
```

And replace the socket handler (line 867):

```javascript
  socket.on("score_phrases_update", (phrases) => { scoreReviews = phrases; });
```

with:

```javascript
  socket.on("score_phrases_update", (phrases) => { window.scoreReviews = phrases; });
```

- [ ] **Step 4: Point score.js at window.scoreReviews**

In `pikaraoke/static/score.js`, replace the three reads (lines 7, 9, 11):

```javascript
    return { applause: "applause-l.mp3", review: randomPhrase(scoreReviews.low) };
```
```javascript
    return { applause: "applause-m.mp3", review: randomPhrase(scoreReviews.mid) };
```
```javascript
    return { applause: "applause-h.mp3", review: randomPhrase(scoreReviews.high) };
```

with (respectively):

```javascript
    return { applause: "applause-l.mp3", review: randomPhrase(window.scoreReviews.low) };
```
```javascript
    return { applause: "applause-m.mp3", review: randomPhrase(window.scoreReviews.mid) };
```
```javascript
    return { applause: "applause-h.mp3", review: randomPhrase(window.scoreReviews.high) };
```

And replace the write (line 63):

```javascript
    scoreReviews = await r.json();
```

with:

```javascript
    window.scoreReviews = await r.json();
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run --no-sync pytest tests/unit/test_splash_score_reviews_window.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite + lint gate**

Run: `uv run --no-sync pytest tests/ -q` → all green (one new test).
Run: `uv run pre-commit run --config code_quality/.pre-commit-config.yaml --all-files` → clean. If it reformats unrelated files, `git checkout -- .` for everything except this task's two files + the new test before committing.

**Manual test checklist (Task 1):** Load the TV splash page; finish a song with scoring enabled → the score screen renders the review text (low/mid/high phrase) — this exercises `window.scoreReviews` end to end. No console `ReferenceError`. (splash is still a classic script here, so this is a pure behavior-parity check.)

- [ ] **Step 7: Commit**

```bash
git add tests/unit/test_splash_score_reviews_window.py pikaraoke/static/js/splash.js pikaraoke/static/score.js
git commit -m "refactor: move splash scoreReviews onto window so it survives module conversion"
```

---

### Task 2: Convert splash.js to an ES module with the screensaver import

**Problem:** `splash.js` is a classic `<script>` reaching `screensaver.js` via implicit globals. Convert it to `type="module"`, make `screensaver.js` export its two functions, import them, and expose the one inline-HTML-referenced function (`handleConfirmation`) on `window` (module top-level bindings are not auto-attached to `window`). Add an invariant test that no template SPA-links to `/splash`.

**Files:**
- Modify: `pikaraoke/static/screensaver.js` (export 2 functions; add ES-module marker comment)
- Modify: `pikaraoke/static/js/splash.js` (import line at top; `window.handleConfirmation`; drop 2 dead comments)
- Modify: `pikaraoke/templates/splash.html` (splash.js tag → `type="module"`; remove classic screensaver.js tag)
- Test: `tests/unit/test_splash_es_module.py`

**Interfaces:**
- Consumes: `window.scoreReviews` from Task 1 (so `score.js` keeps working under module scope).
- Produces: `splash.js` is now an ES module; `screensaver.js` exports `startScreensaver`/`stopScreensaver`; `window.handleConfirmation` is defined for the inline `onClick` handlers.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_splash_es_module.py`:

```python
import glob
import os

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_SPLASH_JS = os.path.join(_PKG, "static", "js", "splash.js")
_SCREENSAVER = os.path.join(_PKG, "static", "screensaver.js")
_SPLASH_HTML = os.path.join(_PKG, "templates", "splash.html")
_TEMPLATES = os.path.join(_PKG, "templates")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_screensaver_exports_its_functions():
    ss = _read(_SCREENSAVER)
    assert "export function startScreensaver" in ss
    assert "export function stopScreensaver" in ss


def test_splash_js_is_a_module_importing_screensaver():
    splash = _read(_SPLASH_JS)
    assert 'import { startScreensaver, stopScreensaver } from "/static/screensaver.js";' in splash
    # Module top-level bindings are not auto-attached to window; the inline onClick handlers need this.
    assert "window.handleConfirmation = handleConfirmation;" in splash
    # The dead "depends on upstream" comments are gone (dependency is now a real import).
    assert "depends on upstream screensaver.js import" not in splash


def test_splash_html_loads_splash_as_module_and_drops_classic_screensaver():
    html = _read(_SPLASH_HTML)
    assert '<script type="module" src="{{ url_for(\'static\', filename=\'js/splash.js\') }}"></script>' in html
    # The classic screensaver.js body tag is removed (it is imported by the module now).
    assert "filename='screensaver.js'" not in html
    # Both inline handlers remain and both resolve to the single window.handleConfirmation.
    assert html.count('onClick="handleConfirmation()"') == 2


def test_no_template_spa_links_to_splash():
    """splash.js is now an ES module; it must stay direct-load-only. An in-app <a href=".../splash">
    would route through spa-navigation.js, which re-injects splash.js as a CLASSIC <script> -> the
    top-level import throws SyntaxError and the TV page renders blank."""
    import re

    for path in glob.glob(os.path.join(_TEMPLATES, "**", "*.html"), recursive=True):
        html = _read(path)
        assert re.search(r'href=["\'][^"\']*/splash\b', html) is None, f"SPA-eligible /splash link in {path}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_splash_es_module.py -v`
Expected: FAIL on the export/import/module-tag assertions (the invariant test should already pass — there is no `/splash` link today; that one is a guard against future regressions).

- [ ] **Step 3: Export the screensaver functions**

In `pikaraoke/static/screensaver.js`, add an ES-module marker comment at the very top of the file (before any code):

```javascript
// ES module: imported by splash.js. Do NOT load this with a classic <script src> — the export
// keywords below are a SyntaxError in classic script context.
```

Then add `export` to the two function declarations (lines 51, 56):

```javascript
export function startScreensaver() {
```
```javascript
export function stopScreensaver() {
```

(Leave `getNewRandomColor`/`animate`/all module-private state unchanged — they are not referenced cross-file.)

- [ ] **Step 4: Make splash.js a module that imports screensaver and exposes handleConfirmation**

In `pikaraoke/static/js/splash.js`, add as the very first line of the file:

```javascript
import { startScreensaver, stopScreensaver } from "/static/screensaver.js";
```

Immediately after the `handleConfirmation` definition (the `const handleConfirmation = () => { ... };` block ending around line 122), add:

```javascript
window.handleConfirmation = handleConfirmation;
```

Remove the two now-dead trailing comments on the screensaver call sites (lines 329, 335): change `startScreensaver(); // depends on upstream screensaver.js import` to `startScreensaver();` and `stopScreensaver(); // depends on upstream screensaver.js import` to `stopScreensaver();`.

- [ ] **Step 5: Update splash.html script tags**

In `pikaraoke/templates/splash.html`, change the splash.js tag (line 35):

```html
<script src="{{ url_for('static', filename='js/splash.js') }}"></script>
```

to:

```html
<script type="module" src="{{ url_for('static', filename='js/splash.js') }}"></script>
```

And remove the classic screensaver.js body tag entirely (line 272):

```html
<script src="{{  url_for('static', filename='screensaver.js') }}"></script>
```

- [ ] **Step 6: Run the new test to verify it passes**

Run: `uv run --no-sync pytest tests/unit/test_splash_es_module.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Run the full suite + lint gate**

Run: `uv run --no-sync pytest tests/ -q` → all green.
Run: `uv run pre-commit run --config code_quality/.pre-commit-config.yaml --all-files` → clean (drop unrelated formatter churn with `git checkout -- .` before committing, keeping only this task's files + the new test).

**Manual test checklist (Task 2) — load the TV splash page directly in a browser:**
- DevTools console: **no `ReferenceError`** for `startScreensaver`, `stopScreensaver`, `handleConfirmation`, `scoreReviews`, or any library global (`Hls`, `SubtitlesOctopus`, `PitchAnalyzer`, `PitchMeter`, `startScore`, `launchFireworkShow`, `getSemitonesLabel`, `setUserCookie`).
- Idle the page past the screensaver timeout → DVD-bounce screensaver starts; move mouse / start a song → it stops.
- Click the permissions-modal confirm — **both** the `confirm` text link (splash.html:204) and the button (splash.html:211) → background media + now-playing load trigger (exercises `window.handleConfirmation`).
- Play a song: HLS video plays, subtitles render, pitch/scoring work; finish a scored song → score screen + review text render (exercises `window.scoreReviews` under module scope).
- **Multi-screen:** open two splash screens → exactly one is assigned master and `register_splash` is not double-emitted (check server logs). This guards the defer-timing change the analysis flagged; if doubled, escalate (do not patch in this slice).

- [ ] **Step 8: Commit**

```bash
git add tests/unit/test_splash_es_module.py pikaraoke/static/screensaver.js pikaraoke/static/js/splash.js pikaraoke/templates/splash.html
git commit -m "refactor: convert splash.js to ES module importing screensaver.js"
```

---

## Self-Review

- **Spec coverage:** Implements analysis-doc §4 (the corrected, atomic slice 1) as two behavior-preserving steps. The critic's CRITICAL `scoreReviews` break is neutralized by Task 1 *before* the module conversion in Task 2. The two Important findings are covered: SPA-invariant → `test_no_template_spa_links_to_splash`; multi-screen double-`register_splash` → Task 2 manual checklist. Minor findings (inline-handler count, bare-global audit) → `onClick` count assertion + manual no-ReferenceError check. Deferred items (bg-media/scoring/etc. extraction, socket stale-closure, idempotent handlers) are explicitly out of scope per Global Constraints and the 9-slice order.
- **Placeholder scan:** none — every step shows exact before/after code.
- **Type/name consistency:** `window.scoreReviews`, `startScreensaver`/`stopScreensaver`, `window.handleConfirmation`, the `import ... from "/static/screensaver.js"` specifier, and the `type="module"` tag are used identically across tasks and tests.
- **Ordering:** Task 1 must land before Task 2 (the module conversion is only safe once `scoreReviews` is on `window`). Each task's intermediate state is fully working.
