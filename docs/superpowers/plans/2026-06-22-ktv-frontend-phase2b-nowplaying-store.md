# KTV Frontend Refactor — Phase 2b (slice 2): nowPlayingStore + songpicker — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce `core/nowPlayingStore` (a single source of truth for the now-playing state that owns the `now_playing` socket subscription + the `/now_playing` HTTP fetch) and migrate the simplest consumer (`songpicker`) to it, removing songpicker's duplicated socket handler + initial fetch/parse.

**Architecture:** `core/nowPlayingStore.js` is an ES module (consumed at RUNTIME, so the deferred-module pattern is fine — unlike `core/socketClient.js` which had to be a classic parse-time global). It is imported in base.html's existing module bootstrap and exposed as `window.nowPlayingStore`. It wires its own `now_playing` listener on the shared `window.getSocket()` singleton and **re-wires defensively on every `subscribe()`** (self-healing, because another page — queueview — clears `now_playing` listeners with a blunt `socket.off("now_playing")`). Subscribers register by a string key (idempotent across SPA navigation — re-subscribing the same key replaces).

**Tech Stack:** Vanilla JS + jQuery (global), native ES modules, socket.io client. Tests: pytest content assertions.

## Global Constraints

- **Branch:** `refactor/ktv-frontend`. NEVER commit to `master`/`main`. New commit per task (no amend).
- **Test command:** `uv run --no-sync pytest tests/ -q` (currently 773 passing) or per-file. `--no-sync` required.
- **No JS test runner** — new JS is manual-review only. Lint Python via pre-commit. (Note: the repo's `pylint` pre-commit hook is a no-op; isort/black/pycln do run.)
- **Commits:** Conventional Commits. No emoji.
- **No server change.** The `/now_playing` route and the `now_playing` socket event are unchanged; this only changes client consumption.
- **Idempotency:** subscribers are keyed (re-subscribe replaces); the store re-wires its socket listener with the specific handler reference (`socket.off("now_playing", handler)` before `on`) so it never double-binds and self-heals after another page's blunt `off("now_playing")`.
- **Scope:** only `songpicker` migrates in this slice. `queueview` (which couples queue + now-playing in one `queuePage_getQueue` fetch, and binds at parse time) and `splash` are deferred — their clean migration is easier after the SPA-loader → MPA change.
- **Manual smoke deferred to the human controller** (no JS runner): the tests assert wiring; behavior (songpicker mini-strip updates live + on load) is the controller's check.

---

## Task Overview

| # | Task | Risk |
|---|------|------|
| 1 | Add `core/nowPlayingStore.js` + base.html bootstrap | low |
| 2 | Migrate `songpicker` now-playing to the store | low-medium |

---

### Task 1: Add `core/nowPlayingStore.js` and bootstrap it

**Files:**
- Create: `pikaraoke/static/core/nowPlayingStore.js`
- Modify: `pikaraoke/templates/base.html` (extend the existing `<script type="module">` bootstrap, lines 19-22)
- Test: `tests/unit/test_nowplaying_store.py` (new)

**Interfaces:**
- Produces: `window.nowPlayingStore` with `subscribe(key, cb)`, `refresh()`, `getState()`. `subscribe` registers `cb` under `key` (replacing any prior cb for that key), ensures the socket listener is wired, and immediately invokes `cb` with the current state (or triggers a `refresh()` if no state yet). The store normalizes the socket payload (object) and the HTTP payload (JSON string) to a plain object.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_nowplaying_store.py`:

```python
import os

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_BASE = os.path.join(_PKG, "templates", "base.html")
_STORE = os.path.join(_PKG, "static", "core", "nowPlayingStore.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_store_module_exists_and_exports_api():
    js = _read(_STORE)
    assert "export function subscribe(" in js
    assert "export function refresh(" in js


def test_base_html_bootstraps_store():
    base = _read(_BASE)
    assert 'import * as nowPlayingStore from "core/nowPlayingStore.js";' in base
    assert "window.nowPlayingStore = nowPlayingStore;" in base
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --no-sync pytest tests/unit/test_nowplaying_store.py -q`
Expected: FAIL (store file missing; base.html has no store bootstrap).

- [ ] **Step 3: Create `core/nowPlayingStore.js`**

Create `pikaraoke/static/core/nowPlayingStore.js`:

```javascript
// Single source of truth for the now-playing state.
// Owns the "now_playing" socket subscription and the /now_playing HTTP fetch so
// individual pages don't each fetch/parse it. ES module, consumed at runtime.
//
// Re-wires its socket listener on every subscribe(): the socket is a shared
// singleton and another page (queueview) clears its now_playing listeners with a
// blunt socket.off("now_playing"), so the store must defensively re-bind. The
// handler reference is passed to off()/on() so it never double-binds.
let _state = null;
const _subs = new Map(); // key -> callback

function _emit() {
  _subs.forEach(function (cb) {
    try {
      cb(_state);
    } catch (e) {
      /* one bad subscriber must not break the others */
    }
  });
}

function _onNowPlaying(np) {
  // socket payload is an already-parsed object
  _state = np;
  _emit();
}

function _wireSocket() {
  const getSocket = window.getSocket;
  const socket = getSocket && getSocket();
  if (!socket) {
    return;
  }
  socket.off("now_playing", _onNowPlaying);
  socket.on("now_playing", _onNowPlaying);
}

export function refresh() {
  const $ = window.jQuery;
  if (!$) {
    return;
  }
  $.get("/now_playing", function (data) {
    try {
      _state = typeof data === "string" ? JSON.parse(data) : data;
      _emit();
    } catch (e) {
      /* ignore malformed payloads */
    }
  });
}

export function subscribe(key, cb) {
  _subs.set(key, cb);
  _wireSocket();
  if (_state) {
    try {
      cb(_state);
    } catch (e) {
      /* ignore */
    }
  } else {
    refresh();
  }
}

export function getState() {
  return _state;
}
```

- [ ] **Step 4: Bootstrap it in base.html**

In `pikaraoke/templates/base.html`, extend the existing module bootstrap (lines 19-22) to also import and expose the store:

```html
  <script type="module">
    import { notify } from "core/ui.js";
    import * as nowPlayingStore from "core/nowPlayingStore.js";
    window.showNotification = notify;
    window.nowPlayingStore = nowPlayingStore;
  </script>
```

- [ ] **Step 5: Run the tests, then the full suite**

Run: `uv run --no-sync pytest tests/unit/test_nowplaying_store.py -q`
Expected: PASS.
Run: `uv run --no-sync pytest tests/ -q`
Expected: PASS (suite green; this only adds a module + bootstrap line).

- [ ] **Step 6: Commit**

```bash
git add pikaraoke/static/core/nowPlayingStore.js pikaraoke/templates/base.html tests/unit/test_nowplaying_store.py
git commit -m "feat: add core/nowPlayingStore single source of truth"
```

---

### Task 2: Migrate songpicker now-playing to the store

`songpicker.html`'s "Mini control strip: now playing" block binds its own `now_playing` socket handler (line 247) and does an initial `$.get` of `/now_playing` (lines 268-271). Replace both with one `window.nowPlayingStore.subscribe(...)`. Keep the `processing_progress` handler, `_renderSpProgress`, `updateMiniStrip`, and the `var sock = window.getSocket()` line (still needed for `processing_progress`).

**Files:**
- Modify: `pikaraoke/templates/songpicker.html` (lines 247 and 268-271)
- Test: `tests/unit/test_nowplaying_store.py` (add assertions)

**Interfaces:**
- Consumes: `window.nowPlayingStore.subscribe(key, cb)` from Task 1.

- [ ] **Step 1: Add the failing assertions**

Append to `tests/unit/test_nowplaying_store.py`:

```python
_SONGPICKER = os.path.join(_PKG, "templates", "songpicker.html")


def test_songpicker_uses_store_for_now_playing():
    html = _read(_SONGPICKER)
    assert 'window.nowPlayingStore.subscribe("songpicker-mini", updateMiniStrip);' in html
    # songpicker no longer binds its own now_playing socket handler or fetches /now_playing itself
    assert 'sock.on("now_playing"' not in html
    assert "updateMiniStrip(JSON.parse(data))" not in html
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_nowplaying_store.py::test_songpicker_uses_store_for_now_playing -q`
Expected: FAIL (songpicker still has its own `sock.on("now_playing"` and the initial `$.get`).

- [ ] **Step 3: Replace the now-playing socket handler with the store subscription**

In `pikaraoke/templates/songpicker.html`, change the now-playing handler line (line 247) from:

```javascript
    sock.off("now_playing"); sock.on("now_playing", function (np) { updateMiniStrip(np); });
```

to:

```javascript
    window.nowPlayingStore.subscribe("songpicker-mini", updateMiniStrip);
```

(`updateMiniStrip` is a hoisted function declaration in the same `$(function(){...})` scope, so it is in scope here.)

- [ ] **Step 4: Remove the now-redundant initial fetch**

Delete the initial-load fetch (lines 268-271, the `// Initial load` comment and the `$.get(...now_playing...)` call) — the store's `subscribe()` performs the initial `refresh()` itself:

```javascript
    // Initial load
    $.get("{{ url_for('now_playing.now_playing') }}", function (data) {
      updateMiniStrip(JSON.parse(data));
    });
```

Leave the surrounding `if (typeof io !== "undefined") { ... }` block, the `var sock = window.getSocket()` line, the `processing_progress` handler, `_renderSpProgress`, and `updateMiniStrip` intact.

- [ ] **Step 5: Run the tests, then the full suite**

Run: `uv run --no-sync pytest tests/unit/test_nowplaying_store.py -q`
Expected: PASS (all assertions across the file).
Run: `uv run --no-sync pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Manual smoke (deferred to human controller)**

Note in the report that the controller should verify: on `/songpicker` the now-playing mini-strip still shows the current song on load and updates live when the song changes; navigate `/songpicker → /queue → /songpicker` a few times and confirm it still updates exactly once per change (the keyed subscriber + self-healing re-wire prevent duplicates/loss).

- [ ] **Step 7: Commit**

```bash
git add pikaraoke/templates/songpicker.html tests/unit/test_nowplaying_store.py
git commit -m "refactor: use nowPlayingStore in songpicker mini-strip"
```

---

## Phase 2b (slice 2) Done — Definition

- `uv run --no-sync pytest tests/ -q` green (773 baseline + the new store tests).
- `window.nowPlayingStore` exists and owns the `now_playing` socket subscription + `/now_playing` fetch.
- `songpicker` consumes the store and no longer binds its own `now_playing` handler or fetches `/now_playing`.
- No server/route/UI behavior change; the human controller has smoke-verified `/songpicker` live updates.

## Deferred (later slices)
- Migrate `queueview` (split its `queuePage_getQueue` into a queue fetch + a `nowPlayingStore` subscription) and `splash` (Phase 3) to the store — cleanest after the SPA-loader → MPA change.
- Bottom-tab IA (點歌/排隊/計分/更多, incl. a dedicated 計分 page); offline-vendor SortableJS; the duet 2nd-singer entry in songpicker.
