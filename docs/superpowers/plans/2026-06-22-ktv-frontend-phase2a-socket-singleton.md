# KTV Frontend Refactor — Phase 2a: Socket-Client Singleton — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the scattered per-page `io()` socket initializations on the two remote pages (`queueview.html`, `songpicker.html`) with a single shared `window.getSocket()` singleton, and fix `songpicker`'s listener-leak — all behavior-preserving (no UI change).

**Architecture:** Add `pikaraoke/static/core/socketClient.js` as a **classic** `<script>` (NOT an ES module) loaded in `base.html` head, so `window.getSocket` is available to the classic page scripts at parse time. (ES modules are deferred and run after the page's parse-time `io()` call, which is why the Phase-1 `core/ui.js` module pattern cannot be used here — see Global Constraints.) The pages call `window.getSocket()` instead of `io()`. The socket.io client library (`socket.io-4.8.3.min.js`) is already loaded globally in `base.html`, providing the global `io`.

**Tech Stack:** Vanilla JS + jQuery (global, classic scripts), socket.io 4.8.3 client, Flask/Jinja2 templates. Tests: pytest content-assertions (no JS test runner exists).

## Global Constraints

- **Branch:** all work stays on `refactor/ktv-frontend`. NEVER commit to `master`/`main`.
- **Test command (local):** `uv run --no-sync pytest tests/ -q` (whole suite, currently 759 passing) or `uv run --no-sync pytest tests/unit/test_X.py -q` (one file). `--no-sync` avoids re-syncing AI extras.
- **No JS/CSS/HTML linter** exists (no package.json/eslint). New JS is manual-review only. Lint Python with `uv run pre-commit run --config code_quality/.pre-commit-config.yaml --all-files`.
- **Commits:** Conventional Commits (`build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test`; header ≤150 chars).
- **No emoji / unicode emoji substitutes** anywhere.
- **Behavior-preserving:** this phase changes NO server code, NO templates' rendered output beyond the socket wiring, and NO visible UI. The socket event flow must remain identical. There is no JS test runner, so each task's behavioral correctness is confirmed by a **manual smoke check deferred to the human controller** (the automated tests assert the wiring only).
- **Deliberate exception:** `core/socketClient.js` is a **classic global script**, not an ES module like `core/ui.js`. This is intentional — the page scripts call `getSocket()` at parse time, before any deferred ES module runs. This exception is reconciled later when the pages themselves become ES modules (the deferred SPA-loader → MPA phase). Do not convert it to an ES module in this phase.
- **Singleton semantics:** `window.getSocket()` returns one memoized `io()` instance for the lifetime of the page, and `null` if the `io` global is unavailable. Because the socket is now shared and long-lived across SPA navigations, every per-page listener MUST be bound idempotently (`socket.off(EVENT)` before `socket.on(EVENT, ...)`) to avoid duplicate-handler stacking.

---

## Task Overview

| # | Task | Risk |
|---|------|------|
| 1 | Add `core/socketClient.js` (classic `window.getSocket` singleton) + load it in `base.html` | low |
| 2 | Migrate `queueview.html` to `window.getSocket()` | low (already uses `off()+on()`) |
| 3 | Migrate `songpicker.html` to `window.getSocket()` + make its 2 listeners idempotent | low-medium (adds `off()` to prevent leak) |

> **Scope note:** `splash.js`'s socket (`let socket = io()` + visibilitychange reconnect) is intentionally NOT migrated here — it is the Phase-3 (splash modularization) target. `core/nowPlayingStore` (centralizing the duplicated `/now_playing` fetch/parse) is deferred to a later phase; this phase is socket-singleton only.

---

### Task 1: Add `core/socketClient.js` and load it in `base.html`

**Files:**
- Create: `pikaraoke/static/core/socketClient.js`
- Modify: `pikaraoke/templates/base.html` (add one classic `<script src>` after the socket.io lib include at line 13)
- Test: `tests/unit/test_socket_client.py` (new)

**Interfaces:**
- Produces: global `window.getSocket()` → returns a single memoized `io()` instance (or `null` if `io` is undefined). Available at parse time on every page that extends `base.html`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_socket_client.py` (content assertions, mirroring `tests/unit/test_module_bootstrap.py`):

```python
import os

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_BASE = os.path.join(_PKG, "templates", "base.html")
_SOCKET = os.path.join(_PKG, "static", "core", "socketClient.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_socket_client_module_exists_and_defines_get_socket():
    js = _read(_SOCKET)
    assert "window.getSocket" in js
    assert "function getSocket(" in js


def test_base_html_loads_socket_client_as_classic_script():
    base = _read(_BASE)
    assert "core/socketClient.js" in base
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-sync pytest tests/unit/test_socket_client.py -q`
Expected: FAIL (`socketClient.js` does not exist → `FileNotFoundError`; `base.html` has no `core/socketClient.js` reference).

- [ ] **Step 3: Create `core/socketClient.js`**

Create `pikaraoke/static/core/socketClient.js`:

```javascript
// Single shared Socket.IO connection for the whole app.
// Replaces the per-page io() calls scattered across the templates so that one
// long-lived connection is reused across SPA navigations.
//
// This is a CLASSIC script (not an ES module): page scripts call getSocket() at
// parse time, before deferred module bootstraps run, so the global must be
// defined synchronously in the document head. The socket.io client library is
// loaded as a classic <script> before this file, providing the global `io`.
(function () {
  var _socket = null;

  function getSocket() {
    if (typeof io === "undefined") {
      return null;
    }
    if (!_socket) {
      _socket = io();
    }
    return _socket;
  }

  window.getSocket = getSocket;
})();
```

- [ ] **Step 4: Load it in `base.html` head**

In `pikaraoke/templates/base.html`, add the classic script immediately after the socket.io library include (line 13), before `spa-navigation.js`:

```html
  <script src="{{  url_for('static', filename='socket.io-4.8.3.min.js') }}"></script>
  <script src="{{  url_for('static', filename='core/socketClient.js') }}"></script>
  <script src="{{  url_for('static', filename='spa-navigation.js') }}"></script>
```

- [ ] **Step 5: Run the tests, then the full suite**

Run: `uv run --no-sync pytest tests/unit/test_socket_client.py -q`
Expected: PASS.
Run: `uv run --no-sync pytest tests/ -q`
Expected: PASS (suite stays green; this only adds a script include).

- [ ] **Step 6: Commit**

```bash
git add pikaraoke/static/core/socketClient.js pikaraoke/templates/base.html tests/unit/test_socket_client.py
git commit -m "feat: add core/socketClient.js window.getSocket singleton"
```

---

### Task 2: Migrate `queueview.html` to `window.getSocket()`

`queueview.html` already binds its listeners idempotently with `off()+on()` (lines 299-314), so it is safe to share the singleton without further listener changes. Only the init at line 8 changes.

**Files:**
- Modify: `pikaraoke/templates/queueview.html:8`
- Test: `tests/unit/test_socket_client.py` (add assertions)

**Interfaces:**
- Consumes: `window.getSocket()` from Task 1.

- [ ] **Step 1: Add the failing assertions**

Append to `tests/unit/test_socket_client.py`:

```python
_QUEUEVIEW = os.path.join(_PKG, "templates", "queueview.html")


def test_queueview_uses_socket_singleton():
    html = _read(_QUEUEVIEW)
    assert "window.socket = window.getSocket();" in html
    assert "window.socket = io()" not in html
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_socket_client.py::test_queueview_uses_socket_singleton -q`
Expected: FAIL (`queueview.html` still has `window.socket = io()`).

- [ ] **Step 3: Edit `queueview.html:8`**

Replace the parse-time init:

```html
  if (typeof window.socket === 'undefined') { window.socket = window.getSocket(); }
```

(Was `if (typeof window.socket === 'undefined') { window.socket = io(); }`. The guard is kept; `getSocket()` is itself memoized so this is idempotent. Leave the `pitch_shift` emit guard at line 16 — `if (typeof io !== 'undefined' && window.socket)` — unchanged; it still works.)

- [ ] **Step 4: Run the test, then the full suite**

Run: `uv run --no-sync pytest tests/unit/test_socket_client.py -q`
Expected: PASS.
Run: `uv run --no-sync pytest tests/ -q`
Expected: PASS.

- [ ] **Step 5: Manual smoke (deferred to human controller)**

Note in the report that the controller should verify: load `/queue`, confirm the queue + now-playing mini-player still update live (queue add/skip), and that processing-progress still shows. (No JS test harness exists.)

- [ ] **Step 6: Commit**

```bash
git add pikaraoke/templates/queueview.html tests/unit/test_socket_client.py
git commit -m "refactor: use socket singleton in queueview.html"
```

---

### Task 3: Migrate `songpicker.html` to `window.getSocket()` + idempotent listeners

`songpicker.html` binds `now_playing` and `processing_progress` **without** `off()` (lines 224-229). With a shared persistent singleton, re-running this script on SPA navigation would stack duplicate handlers. So the migration both swaps `io()` for `window.getSocket()` AND adds `off()` before each `on()`.

**Files:**
- Modify: `pikaraoke/templates/songpicker.html:223-225`
- Test: `tests/unit/test_socket_client.py` (add assertions)

**Interfaces:**
- Consumes: `window.getSocket()` from Task 1.

- [ ] **Step 1: Add the failing assertions**

Append to `tests/unit/test_socket_client.py`:

```python
_SONGPICKER = os.path.join(_PKG, "templates", "songpicker.html")


def test_songpicker_uses_socket_singleton_and_idempotent_listeners():
    html = _read(_SONGPICKER)
    assert "var sock = window.getSocket();" in html
    assert "var sock = io();" not in html
    assert 'sock.off("now_playing");' in html
    assert 'sock.off("processing_progress");' in html
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_socket_client.py::test_songpicker_uses_socket_singleton_and_idempotent_listeners -q`
Expected: FAIL (`songpicker.html` still has `var sock = io();` and no `off()` calls).

- [ ] **Step 3: Edit `songpicker.html:223-225`**

Change the socket init and make both listeners idempotent. The block becomes:

```javascript
  if (typeof io !== "undefined") {
    var sock = window.getSocket();
    sock.off("now_playing"); sock.on("now_playing", function (np) { updateMiniStrip(np); });
    sock.off("processing_progress"); sock.on("processing_progress", function (data) {
      if (!data) return;
      window._lastProcessingProgress = data;
      _renderSpProgress(data);
    });
```

(Only lines 223-225 change: `var sock = io();` → `var sock = window.getSocket();`, and an `off()` is prepended to each of the two `on()` bindings. The outer `if (typeof io !== "undefined")` guard, the `_renderSpProgress` function, the progress-restore block, and the initial `$.get(...now_playing...)` load all remain unchanged.)

- [ ] **Step 4: Run the test, then the full suite**

Run: `uv run --no-sync pytest tests/unit/test_socket_client.py -q`
Expected: PASS (all assertions across the file).
Run: `uv run --no-sync pytest tests/ -q`
Expected: PASS.

- [ ] **Step 5: Manual smoke (deferred to human controller)**

Note in the report that the controller should verify: load `/songpicker`, confirm the now-playing mini-strip updates live; navigate away to `/queue` and back to `/songpicker` a few times and confirm the mini-strip updates exactly once per change (no duplicate/double rendering — the regression this `off()` change prevents).

- [ ] **Step 6: Commit**

```bash
git add pikaraoke/templates/songpicker.html tests/unit/test_socket_client.py
git commit -m "refactor: use socket singleton in songpicker.html and bind listeners idempotently"
```

---

## Phase 2a Done — Definition

- `uv run --no-sync pytest tests/ -q` is green (759 baseline + the new Task 1-3 content tests).
- `window.getSocket()` is the single socket factory; `queueview.html` and `songpicker.html` no longer call `io()` directly.
- `songpicker.html`'s `now_playing`/`processing_progress` listeners are idempotent (`off()+on()`).
- No server/template-output/UI behavior changed; the human controller has smoke-verified `/queue` and `/songpicker` live updates.

## Deferred (later phases)
- `splash.js` socket (`let socket = io()` + visibilitychange reconnect) → Phase 3 (splash modularization); once on the singleton, the manual reconnect-and-rebind logic can be retired (socket.io auto-reconnects a persistent connection).
- `core/nowPlayingStore` (centralize the 4 duplicated `/now_playing` fetch/parse/diff sites: `queueview.html:91`, `songpicker.html:246`, `splash.js:520`, `splash.js:788`) → pairs with the mini-player render unification in the page-rework phase.
- Replace `core/socketClient.js`'s classic-global form with an ES-module import once the pages become ES modules (MPA phase).
