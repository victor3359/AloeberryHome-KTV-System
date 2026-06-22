# KTV Frontend Refactor — Phase 1: Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lay a low-risk foundation for the KTV frontend refactor: fix the random-mic-scoring backend bug, delete the two truly-dead templates, apply the Neon Night design tokens, and stand up the native-ES-module + import-map infrastructure via a first `core/` slice (unified notifications).

**Architecture:** Keep the Flask/Jinja backend and its socket/JSON contract untouched except for one additive payload field. Introduce native ES modules under `pikaraoke/static/core/` resolved by a `<script type="importmap">` in `base.html` (zero build step). Centralize the design palette in the single `:root` token layer in `pikaraoke/static/modern-theme.css`.

**Tech Stack:** Python 3.10+, Flask + Jinja2, flask-socketio, vanilla JS + jQuery (global, classic scripts), native ES modules + import maps, CSS custom properties. Tests: pytest (`uv`).

## Global Constraints

- **Branch:** all work stays on `refactor/ktv-frontend`. NEVER commit to `master`/`main`.
- **Test command (local):** `uv run --no-sync pytest tests/ -q` (whole suite) or `uv run --no-sync pytest tests/unit/test_X.py -q` (one file). `--no-sync` avoids re-syncing the heavy AI extras (torch/demucs/whisper).
- **Lint:** `uv run pre-commit run --config code_quality/.pre-commit-config.yaml --all-files`. Black line-length 100, isort profile=black. There is **NO** JS/CSS/HTML linter — new frontend code is manual-review only.
- **Commits:** Conventional Commits required (allowed types: `build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test`; header ≤150 chars). A non-conventional subject fails CI.
- **No emoji / unicode emoji substitutes** in code or templates (per `CLAUDE.md`).
- **Type hints:** modern syntax (`str | None`) for any new Python.
- **CSS contract:** the single token source of truth is the `:root` block in `pikaraoke/static/modern-theme.css`. When editing any CSS that has a `?v=` cache-buster in `base.html`, bump the version (`?v=3` → `?v=4`).
- **UI strings:** Traditional Chinese (zh-TW). Phase 1 introduces no user-facing strings of its own (notification text comes from existing callers).
- **Pre-existing test baseline:** the suite is 750 tests, all passing. After Phase 1 it should be 750 + the new tests added here, all passing.

---

## Task Overview

| # | Task | Risk | Touches backend? |
|---|------|------|------------------|
| 1 | Surface `now_playing_filename` in the now-playing payload (fixes random mic scoring) | low | yes (1 additive line) |
| 2 | Delete the two truly-dead templates (`home.html`, `queue.html`) | low | no |
| 3 | Apply the Neon Night palette to the design tokens | low (visual) | no |
| 4 | Stand up ES-module + import-map infra; extract unified notifications into `core/ui.js` | medium | no |

> **Scope note / spec correction:** the design spec lumped `home.html`/`queue.html`/`files.html`/`search.html` as "dead". Recon proved only `home.html` (313 L) and `queue.html` (598 L) are truly unrendered. `files.html` and `search.html` are still reachable via the `/browse_legacy` and `/search_legacy` routes and `search.html` holds the **only** duet-singer input — so they (and their `_legacy` routes) are **deferred to Phase 2**, not deleted here. See the Deferred Appendix for the verbatim snippets being preserved.

---

### Task 1: Surface `now_playing_filename` in the now-playing payload (fix random mic scoring)

The flagship mic-scoring feature scores randomly because `PlaybackController.get_now_playing()` never includes the current song's file path, so `splash.js` fetches `/pitch_data/` with an empty string and the reference pitch curve is never loaded. `splash.js:501` already reads `np.now_playing_filename`; the fix is one additive backend line. No frontend change.

**Files:**
- Modify: `pikaraoke/lib/playback_controller.py:227-240` (the `get_now_playing` returned dict)
- Test: `tests/unit/test_playback_controller.py` (add to `class TestPlaybackControllerGetNowPlaying`, around line 256-275)
- Test (contract): `tests/unit/test_now_playing_routes.py` (the "all required fields" mock + asserts, ~line 38-69)

**Interfaces:**
- Produces: the now-playing payload dict now contains key `"now_playing_filename"` whose value is `self.now_playing_filename` (`str | None`, the full file path of the current song; `None` when nothing plays). The wrapper `Karaoke.get_now_playing()` spreads `**playback_state`, so the field auto-propagates to the `/now_playing` HTTP route and the `now_playing` socket event with no further change. `splash.js:501` consumes `np.now_playing_filename` unchanged.

- [ ] **Step 1: Write the failing unit test**

Add this method inside `class TestPlaybackControllerGetNowPlaying` in `tests/unit/test_playback_controller.py` (mirror the existing `test_get_now_playing_returns_state` style; `EventSystem` and `PlaybackController` are already imported in this file, and `test_prefs` is the existing fixture at lines 12-15):

```python
    def test_get_now_playing_includes_filename(self, test_prefs):
        """get_now_playing must surface now_playing_filename for mic scoring."""
        events = EventSystem()
        filename_fn = lambda x, remove_youtube_id=True: x

        pc = PlaybackController(test_prefs, events, filename_fn)
        pc.now_playing_filename = "/songs/Artist - Song.mp4"

        state = pc.get_now_playing()

        assert state["now_playing_filename"] == "/songs/Artist - Song.mp4"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_playback_controller.py::TestPlaybackControllerGetNowPlaying::test_get_now_playing_includes_filename -q`
Expected: FAIL with `KeyError: 'now_playing_filename'`.

- [ ] **Step 3: Add the field to the payload**

In `pikaraoke/lib/playback_controller.py`, in the dict returned by `get_now_playing()` (lines 227-240), add the `now_playing_filename` line immediately after `"now_playing"`:

```python
        with self._lock:
            return {
                "now_playing": self.now_playing,
                "now_playing_filename": self.now_playing_filename,
                "now_playing_user": self.now_playing_user,
                "now_playing_user2": self.now_playing_user2,
                "now_playing_duration": self.now_playing_duration,
                "now_playing_transpose": self.now_playing_transpose,
                "now_playing_url": self.now_playing_url,
                "now_playing_subtitle_url": self.now_playing_subtitle_url,
                "now_playing_position": self.now_playing_position,
                "now_playing_audio_mode": self.now_playing_audio_mode,
                "supports_multi_audio": self.supports_multi_audio,
                "is_paused": self.is_paused,
            }
```

The attribute `self.now_playing_filename` already exists (declared `now_playing_filename: str | None = None` at line 42, set to the full path in `play_file()` at line 115). The method's return type hint already permits `str | None`, so no signature change.

- [ ] **Step 4: Run the unit test to verify it passes**

Run: `uv run --no-sync pytest tests/unit/test_playback_controller.py::TestPlaybackControllerGetNowPlaying::test_get_now_playing_includes_filename -q`
Expected: PASS.

- [ ] **Step 5: Keep the route contract test complete**

`tests/unit/test_now_playing_routes.py::test_now_playing_returns_all_required_fields` mocks `get_now_playing` entirely, so it documents the expected field set. Add the new field to its mock return dict AND assert it, so the contract list stays exhaustive. In that test, add the key to the `mock_karaoke.get_now_playing.return_value` dict:

```python
            "now_playing": "Artist - Song",
            "now_playing_filename": "/songs/Artist - Song.mp4",
```

and add the assertion alongside the other `assert "..." in data` lines:

```python
        assert "now_playing_filename" in data
```

- [ ] **Step 6: Run both test files to verify they pass**

Run: `uv run --no-sync pytest tests/unit/test_playback_controller.py tests/unit/test_now_playing_routes.py -q`
Expected: PASS (all tests in both files).

- [ ] **Step 7: Commit**

```bash
git add pikaraoke/lib/playback_controller.py tests/unit/test_playback_controller.py tests/unit/test_now_playing_routes.py
git commit -m "fix: surface now_playing_filename in now-playing payload (fixes random mic scoring)"
```

---

### Task 2: Delete the two truly-dead templates (`home.html`, `queue.html`)

Both templates have zero `render_template` references anywhere (verified). The live pages are `queueview.html` (rendered by `/queue` at `queue.py:63`); `home_bp`'s `/` route only `redirect`s to `queue.queue`. Their unique features (persistent transpose UI, leaderboard hide-toggle) are preserved verbatim in this plan's Deferred Appendix for re-implementation in later phases.

**Files:**
- Delete: `pikaraoke/templates/home.html`, `pikaraoke/templates/queue.html`
- Test: `tests/unit/test_dead_templates_removed.py` (new)

**Interfaces:** none produced.

- [ ] **Step 1: Write the failing regression-guard test**

Create `tests/unit/test_dead_templates_removed.py` (computes the templates dir relative to the test file, same idiom as `test_new_features.py`):

```python
import os

_TEMPLATE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "pikaraoke", "templates"
)


def test_dead_home_template_removed():
    """home.html is unrendered (the / route redirects to /queue) — must be gone."""
    assert not os.path.exists(os.path.join(_TEMPLATE_DIR, "home.html"))


def test_dead_queue_template_removed():
    """queue.html is unrendered (the live queue page is queueview.html) — must be gone."""
    assert not os.path.exists(os.path.join(_TEMPLATE_DIR, "queue.html"))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_dead_templates_removed.py -q`
Expected: FAIL (both files still exist).

- [ ] **Step 3: Delete the two dead templates**

```bash
git rm pikaraoke/templates/home.html pikaraoke/templates/queue.html
```

(Do NOT touch `pikaraoke/routes/home.py` or `pikaraoke/routes/queue.py` — the `/` redirect and the `/queue → queueview.html` render must stay.)

- [ ] **Step 4: Run the guard test, then the full suite**

Run: `uv run --no-sync pytest tests/unit/test_dead_templates_removed.py -q`
Expected: PASS.
Run: `uv run --no-sync pytest tests/ -q`
Expected: PASS — the full suite stays green (the live `/queue` and `/` render `queueview.html`, not the deleted files; `test_new_features.py`'s full-render tests hit `/queue` → `queueview.html`).

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_dead_templates_removed.py
git commit -m "refactor: delete dead templates home.html and queue.html (unrendered; live page is queueview.html)"
```

---

### Task 3: Apply the Neon Night palette to the design tokens

Remap the single `:root` token layer in `pikaraoke/static/modern-theme.css` (lines 11-71, 37 vars — the only `:root` in the project; every template extends `base.html` which loads it, so this instantly restyles the whole app). This is the approved Neon Night palette. Splash-only `themes.css` variants still use the old palette and are **deferred to Phase 3**.

**Files:**
- Modify: `pikaraoke/static/modern-theme.css:11-71` (`:root` token values + 4 new tokens)
- Modify: `pikaraoke/templates/base.html:16` (cache-buster `?v=3` → `?v=4`)
- Test: `tests/unit/test_design_tokens.py` (new)

**Interfaces:**
- Produces: design tokens now carry Neon Night values. New tokens added: `--accent-2: #e879f9;` (magenta), `--accent-violet: #a78bfa;`, `--panel: rgba(255, 255, 255, 0.06);`, `--panel-border: rgba(255, 255, 255, 0.12);`. Existing token NAMES are unchanged (so the 35 `var()` references keep resolving); only their values change.

- [ ] **Step 1: Write the failing token test**

Create `tests/unit/test_design_tokens.py`:

```python
import os

_CSS = os.path.join(
    os.path.dirname(__file__), "..", "..", "pikaraoke", "static", "modern-theme.css"
)


def _read():
    with open(_CSS, encoding="utf-8") as f:
        return f.read()


def test_neon_night_accent_values_applied():
    css = _read()
    assert "--accent-cyan: #22d3ee;" in css
    assert "--text-primary: #ffffff;" in css
    assert "--color-success: #34d399;" in css


def test_neon_night_new_tokens_added():
    css = _read()
    assert "--accent-2: #e879f9;" in css
    assert "--accent-violet: #a78bfa;" in css
    assert "--panel: rgba(255, 255, 255, 0.06);" in css
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_design_tokens.py -q`
Expected: FAIL (current values are `#06b6d4`, `#f1f5f9`, `#10b981`; new tokens absent).

- [ ] **Step 3: Edit the `:root` token values**

In `pikaraoke/static/modern-theme.css`, apply these exact value changes inside the `:root` block (lines 11-71). Change the listed lines and add the four new tokens (add `--accent-2` and `--accent-violet` to the Accent group, and `--panel`/`--panel-border` to the Glass group):

```css
    /* Background */
    --bg-base: #0a0a12;

    /* Text */
    --text-primary: #ffffff;
    --text-secondary: #9aa3b5;
    --text-tertiary: #7c8499;

    /* Accent */
    --accent-gradient: linear-gradient(135deg, #22d3ee, #e879f9);
    --accent-purple: #a78bfa;
    --accent-cyan: #22d3ee;
    --accent-2: #e879f9;
    --accent-violet: #a78bfa;

    /* Status */
    --color-success: #34d399;
    --color-warning: #facc15;

    /* Borders */
    --border-accent: rgba(34, 211, 238, 0.4);

    /* Glass */
    --panel: rgba(255, 255, 255, 0.06);
    --panel-border: rgba(255, 255, 255, 0.12);

    /* Shadows */
    --shadow-glow: 0 0 20px rgba(34, 211, 238, 0.18);
```

(Leave `--color-danger`, radii, spacing, transitions, typography, `--glass-*`, `--bg-surface*` as-is. Keep the existing group comments; only the values above change, plus the four added token lines.)

- [ ] **Step 4: Bump the CSS cache-buster**

In `pikaraoke/templates/base.html` line 16, change the `modern-theme.css` version so browsers reload:

```html
  <link rel="stylesheet" href="{{  url_for('static', filename='modern-theme.css') }}?v=4">
```

- [ ] **Step 5: Run the token test, then the full suite**

Run: `uv run --no-sync pytest tests/unit/test_design_tokens.py -q`
Expected: PASS.
Run: `uv run --no-sync pytest tests/ -q`
Expected: PASS (CSS changes do not affect Python tests).

- [ ] **Step 6: Manual visual check (no automated UI test exists)**

Run the app and open any page (e.g. the queue/control page) in a browser to confirm the new cyan/magenta palette renders and nothing is unreadable:

```bash
uv run --no-sync pikaraoke
```

Then browse to the printed URL (default `http://localhost:5555/queue`). Confirm accents are cyan `#22d3ee` / magenta and text is legible on the dark background. Stop the server with Ctrl-C. (Splash `themes.css` variants are intentionally untouched until Phase 3.)

- [ ] **Step 7: Commit**

```bash
git add pikaraoke/static/modern-theme.css pikaraoke/templates/base.html tests/unit/test_design_tokens.py
git commit -m "feat: apply Neon Night palette to design tokens"
```

---

### Task 4: Stand up ES-module + import-map infra; extract unified notifications into `core/ui.js`

This is the architectural seed: a `<script type="importmap">` in `base.html` maps the `core/` specifier prefix to `/static/core/`, and the first ES module `core/ui.js` exports the unified `notify()` (replacing the duplicated `showNotification`). A tiny module bootstrap assigns `window.showNotification = notify` so the six templates that call the global keep working with no edits. The dead inline `showNotification` and `connectSocket` are removed from `base.html`.

**Files:**
- Create: `pikaraoke/static/core/ui.js`
- Modify: `pikaraoke/templates/base.html` (add importmap + module bootstrap; remove inline `showNotification` at 62-68 and dead `connectSocket` at 56-60)
- Test: `tests/unit/test_module_bootstrap.py` (new)

**Interfaces:**
- Produces: ES module `core/ui.js` exporting `notify(message, categoryClass, timeout = 3000)`. It targets `#notification-alt` and **no-ops gracefully when that node is absent** (blank pages like splash). Import map: `{ "imports": { "core/": "/static/core/" } }`. Global shim: `window.showNotification = notify` (so `files.html`, `info.html`, `search.html`, `songpicker.html`, `batch-song-renamer.html` and any other global callers keep working).

**Ordering note (why this is safe):** deferred classic scripts (jQuery) and module scripts both execute after HTML parse and **before** `DOMContentLoaded`; jQuery `$(fn)` ready handlers fire on `DOMContentLoaded`. So `window.showNotification` is assigned by the module before any ready-handler caller runs. `core/ui.js` reads `window.jQuery` at call time (not import time), by which point jQuery's classic script has loaded.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_module_bootstrap.py` (raw-file content assertions — deterministic, no Flask render needed):

```python
import os

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_BASE = os.path.join(_PKG, "templates", "base.html")
_UI = os.path.join(_PKG, "static", "core", "ui.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_base_html_declares_import_map():
    base = _read(_BASE)
    assert 'type="importmap"' in base
    assert '"core/": "/static/core/"' in base


def test_base_html_bootstraps_core_ui_module():
    base = _read(_BASE)
    assert 'import { notify } from "core/ui.js";' in base
    assert "window.showNotification = notify;" in base


def test_base_html_inline_shownotification_removed():
    base = _read(_BASE)
    assert "function showNotification(" not in base
    assert "function connectSocket(" not in base


def test_core_ui_module_exists_and_exports_notify():
    ui = _read(_UI)
    assert "export function notify(" in ui
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/unit/test_module_bootstrap.py -q`
Expected: FAIL (`core/ui.js` does not exist → `FileNotFoundError`; importmap/bootstrap not in `base.html`; inline `showNotification` still present).

- [ ] **Step 3: Create the `core/ui.js` module**

Create `pikaraoke/static/core/ui.js`:

```javascript
// Unified user-facing notifications.
// Replaces the duplicated showNotification (base.html + spa-navigation.js).
// Reads window.jQuery at call time; no-ops gracefully when the node is absent
// (blank pages such as the splash screen have no #notification-alt).

const NOTIFICATION_SELECTOR = "#notification-alt";

export function notify(message, categoryClass, timeout = 3000) {
  const $ = window.jQuery;
  if (!$) {
    return;
  }
  const node = $(NOTIFICATION_SELECTOR);
  if (node.length === 0) {
    return;
  }
  node.addClass(categoryClass);
  node.find("div").text(message);
  node.fadeIn();
  setTimeout(function () {
    node.fadeOut();
  }, timeout);
  setTimeout(function () {
    node.removeClass(categoryClass);
  }, timeout + 750);
}
```

- [ ] **Step 4: Add the import map + module bootstrap to `base.html`**

In `pikaraoke/templates/base.html`, immediately after the existing vendored `<script>` includes (after the `spa-navigation.js` line, around line 14), insert:

```html
  <script type="importmap">
  { "imports": { "core/": "/static/core/" } }
  </script>
  <script type="module">
    import { notify } from "core/ui.js";
    window.showNotification = notify;
  </script>
```

- [ ] **Step 5: Remove the dead inline functions from `base.html`**

In the inline `<script>` block of `base.html`, delete the now-superseded `showNotification` (lines 62-68) and the dead, never-called `connectSocket` (lines 56-60). Remove exactly these two blocks:

```javascript
    function connectSocket() {
      socket = io();
      socket.on('connect', function() { console.log('Socket connected'); });
      socket.on('disconnect', function() { console.log('Socket disconnected'); });
    }
```

```javascript
    function showNotification(message, categoryClass, timeout=3000) {
      $("#notification-alt").addClass(categoryClass)
      $("#notification-alt div").text(message)
      $("#notification-alt").fadeIn()
      setTimeout(function () {$("#notification-alt").fadeOut()}, timeout)
      setTimeout(function () {$("#notification-alt").removeClass(categoryClass)}, timeout + 750)
    }
```

(Leave the other inline helpers — `debounce`, `getSemitonesLabel`, cookie helpers, DOM-ready handlers — untouched; they move in later phases.)

- [ ] **Step 6: Run the module-bootstrap tests, then the full suite**

Run: `uv run --no-sync pytest tests/unit/test_module_bootstrap.py -q`
Expected: PASS (all four tests).
Run: `uv run --no-sync pytest tests/ -q`
Expected: PASS (full suite green).

- [ ] **Step 7: Manual smoke check (no JS test harness exists)**

```bash
uv run --no-sync pikaraoke
```

In a browser: (a) on the control page (`/queue`), trigger an action that shows a toast (e.g. add or remove a song) and confirm the `#notification-alt` toast still appears; (b) open `/splash` and confirm there is no JavaScript console error (the toast `notify()` no-ops there because `#notification-alt` is absent). Stop with Ctrl-C.

- [ ] **Step 8: Commit**

```bash
git add pikaraoke/static/core/ui.js pikaraoke/templates/base.html tests/unit/test_module_bootstrap.py
git commit -m "refactor: add ES-module import-map infra and extract notifications into core/ui.js"
```

---

## Phase 1 Done — Definition

- `uv run --no-sync pytest tests/ -q` is green (750 baseline + the new Task 1-4 tests).
- `uv run pre-commit run --config code_quality/.pre-commit-config.yaml --all-files` passes (run it once before opening a PR; Python files only — JS/CSS are not linted).
- Mic scoring loads a real reference pitch curve when `_pitch.json` exists (the random-score bug is fixed).
- `home.html` and `queue.html` are gone; the app still serves `/` and `/queue`.
- The whole UI renders in the Neon Night palette via the token layer.
- `base.html` carries the import map and the first `core/` module; the duplicated/dead inline functions are removed.

---

## Deferred Appendix (preserved for later phases)

### Deferred to Phase 2 — legacy templates + their routes
`files.html` (218 L, rendered by `/browse_legacy` at `files.py:68-171`) and `search.html` (749 L, rendered by `/search_legacy` at `search.py:48-70`) are reachable-but-legacy. Delete them together with their `_legacy` route functions during the discovery/browse rework — AND first port the duet input below into `songpicker.html`.

### Deferred — duet / 2nd-singer input (only lives in legacy `search.html`)
`songpicker.html` only *displays* `user2`; the only entry field is in `search.html`. Port this when reworking songpicker (Phase 2):

```html
<!-- search.html:599-603 -->
<input class="song_added_by" type="hidden" name="song_added_by" />
<input class="song-added-by-2" type="hidden" name="song_added_by_2" />
<div class="control" style="margin-top: 6px">
  <input id="duet-singer-2" class="input is-small" type="text" placeholder="Duet with (optional 2nd singer)" style="max-width: 300px" />
</div>
```
```javascript
// search.html:426-429 — sync visible field into the hidden submit field
$("#duet-singer-2").on("input", function () {
  $(".song-added-by-2").val($(this).val().trim());
});
```

### Deferred to Phase 4 — persistent (server-side) transpose UI (only lived in dead `home.html`)
The live `queueview.html` uses client-side `socket.emit('pitch_shift', ...)` (per-song, resets on skip). The persistent server path `GET /transpose/<n>` → `controller.py:38` → `k.transpose_current` had its only caller in `home.html`. Re-implement in `queueview.html` together with cross-song transpose persistence (spec §7), or remove the orphaned `/transpose` route:

```html
<!-- home.html:277-306 (markup) -->
{% if is_transpose_enabled %}
<div class="is-flex" style="justify-content: space-between">
  <div><h4>{% trans %}Change Key{% endtrans %}</h4></div>
  <div class="is-flex"><h4 id="semitones-label"></h4>
    <a id="semitones-info"> <i class="icon icon-info-circled-1" title="Info"></i></a></div>
</div>
<div style="width: 100%"><div class="is-flex">
  <input type="range" min="-12" max="12" value="0" class="transpose-slider" id="transpose" style="width: 100%" />
  <button id="submit-transpose" class="button is-rounded is-small" style="margin-left: 10px">
    {% trans %}Change{% endtrans %}</button>
</div></div>
{% endif %}
```
```javascript
// home.html:99-112 (handler — the only live caller of /transpose)
$("#submit-transpose").click(function () {
  var value = slider ? slider.value : 0;
  if (confirm("Transpose this song: " + getSemitonesLabel(value) + "?")) {
    $.get("/transpose/" + value);
  }
  slider.value = 0;
  output.innerHTML = getSemitonesLabel(slider.value);
});
```

### Deferred to Phase 2/3 — leaderboard hide/toggle (only lived in dead `home.html`)
Live `queueview.html` only *emits* `show_leaderboard` (key `L`); there is no hide. The `hide_leaderboard` socket handler exists (`socket_events.py:86-89`). Port this toggle (button + both emits) into the new control UI:

```html
<!-- home.html:308 -->
<button id="toggle-leaderboard" class="button is-warning is-fullwidth">Show Leaderboard</button>
```
```javascript
// home.html:144-155
var leaderboardVisible = false;
$("#toggle-leaderboard").click(function () {
  if (leaderboardVisible) {
    window.socket.emit("hide_leaderboard");
    $(this).text("Show Leaderboard");
    leaderboardVisible = false;
  } else {
    window.socket.emit("show_leaderboard");
    $(this).text("Hide Leaderboard");
    leaderboardVisible = true;
  }
});
```

### Deferred to Phase 5 — vendor SortableJS for offline
`queueview.html:2` (and the now-deleted `queue.html`) load SortableJS from `cdn.jsdelivr.net/npm/sortablejs@latest`. Download a pinned copy into `pikaraoke/static/` and switch `queueview.html` to the local file (and into the import map) as part of offline hardening.
