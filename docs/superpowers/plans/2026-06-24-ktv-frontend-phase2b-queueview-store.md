# Phase 2b slice 3 — queueview nowPlayingStore migration + idempotent handlers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `queueview.html` consume the shared `nowPlayingStore` for now-playing state (eliminating its third duplicate now-playing fetch/parse) and make its document-delegated click/keydown handlers idempotent so SPA re-navigation stops stacking duplicates.

**Architecture:** Two independent, queueview-only changes. Task 1 namespaces and `.off()`-guards the `$(document)`-level delegated handlers (the only ones that survive SPA content swaps and therefore stack). Task 2 subscribes queueview to `window.nowPlayingStore`, splits now-playing out of the combined queue+now_playing fetch, removes queueview's own `now_playing` socket binding, and DRYs the queue-list re-render into one extracted function shared by the queue-update path and the store callback.

**Tech Stack:** Flask/Jinja templates, jQuery (classic inline `<script>`), native ES module `core/nowPlayingStore.js` already bootstrapped on `window.nowPlayingStore` in `base.html`. Frontend "tests" are Python string-assertion tests over template files (no JS test harness, zero build) — runtime behavior is covered by the per-task manual checklist (this matches the existing convention in `tests/unit/test_socket_client.py`, `test_nowplaying_store.py`, `test_queueview_audio_mode_drawer.py`).

## Global Constraints

- Backend untouched. No new routes, no contract changes. `queue.get_queue` and `now_playing.now_playing` routes already exist.
- Behavior must stay identical: same mini-player, control-panel drawer, queue list, sortable reorder, fair-queue counts, downloads, processing progress, admin-gated actions, keyboard shortcuts.
- No framework. No build step. zh-TW single locale. Keep the socket singleton (`window.socket = window.getSocket()`).
- Follow the existing migration pattern set by songpicker slice 2: subscribe via `window.nowPlayingStore.subscribe("<key>", cb)`; the page must no longer bind its own `now_playing` socket handler nor fetch `/now_playing` itself.
- Code style: 2-space JS indentation matching the surrounding template; no emoji; no commented-out code (delete dead code).
- Quality gate before declaring done: `uv run --no-sync pytest tests/ -q` all green AND `uv run pre-commit run --config code_quality/.pre-commit-config.yaml --all-files` clean.

---

### Task 1: Make queueview document-delegated handlers idempotent

**Problem:** `spa-navigation.js` re-executes queueview's inline `<script>` on every visit. Handlers bound on the persistent `document` (`$(document).on("click", selector, …)` and `$(document).keydown(…)`) are NOT torn down by the SPA content swap, so each visit stacks another copy → a single tap fires the handler N times. Direct binds on `{% block content %}` elements (`#mini-pause-btn`, `#cp-*`, `.mini-player`) are safe — those elements are replaced on nav, taking their handlers with them. The `.confirm-new-session` handler (currently at `queueview.html:301`) already uses the correct `.off(...).on(...)` form and is the model to follow.

**Files:**
- Modify: `pikaraoke/templates/queueview.html` (the 5 document-level handlers: `.queue-song-options-btn`, `.now-playing-options-btn`, `.audio-mode-btn`, `.audio-mode-btn-mini`, and the admin `keydown`)
- Test: `tests/unit/test_queueview_idempotent_handlers.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing other tasks depend on. Task 2 leaves these handlers untouched.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_queueview_idempotent_handlers.py`:

```python
import os

_QV = os.path.join(
    os.path.dirname(__file__), "..", "..", "pikaraoke", "templates", "queueview.html"
)


def _read():
    with open(_QV, encoding="utf-8") as f:
        return f.read()


def test_document_delegated_handlers_are_offed_before_on():
    """SPA re-navigation re-runs this inline script; handlers bound on the persistent
    document stack unless each is removed first. Every $(document)-level click/keydown
    handler must be guarded with a namespaced .off(...) so re-binding is idempotent."""
    html = _read()
    # Namespaced off-guards must exist for each document-delegated handler.
    assert '.off("click.qv", ".queue-song-options-btn")' in html
    assert '.off("click.qv", ".now-playing-options-btn")' in html
    assert '.off("click.qv", ".audio-mode-btn")' in html
    assert '.off("click.qv", ".audio-mode-btn-mini")' in html
    assert '.off("keydown.qv")' in html
    # The old un-guarded delegated forms must be gone.
    assert "$(document).on('click', '.queue-song-options-btn'" not in html
    assert "$(document).on('click', '.now-playing-options-btn'" not in html
    assert '$(document).on("click", ".audio-mode-btn",' not in html
    assert '$(document).on("click", ".audio-mode-btn-mini",' not in html
    assert "$(document).keydown(function" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_queueview_idempotent_handlers.py -v`
Expected: FAIL (the `.off("click.qv", ...)` strings do not exist yet).

- [ ] **Step 3: Convert the two options handlers to namespaced off+on**

In `queueview.html`, inside the `$(function() {` block, replace:

```javascript
    $(document).on('click', '.queue-song-options-btn', function(e) {
      e.preventDefault();
      openSongOptions(parseInt($(this).data('index')), decodeURIComponent($(this).data('file')), decodeURIComponent($(this).data('title')));
    });
    $(document).on('click', '.now-playing-options-btn', function(e) { e.preventDefault(); openNowPlayingOptions(); });
```

with:

```javascript
    $(document).off("click.qv", ".queue-song-options-btn").on("click.qv", ".queue-song-options-btn", function(e) {
      e.preventDefault();
      openSongOptions(parseInt($(this).data('index')), decodeURIComponent($(this).data('file')), decodeURIComponent($(this).data('title')));
    });
    $(document).off("click.qv", ".now-playing-options-btn").on("click.qv", ".now-playing-options-btn", function(e) { e.preventDefault(); openNowPlayingOptions(); });
```

- [ ] **Step 4: Convert the two audio-mode handlers to namespaced off+on**

Replace:

```javascript
    // Audio mode toggle (control panel)
    $(document).on("click", ".audio-mode-btn", function() {
      var mode = $(this).data("mode");
      $.get("/audio_mode/" + mode);
      $(".audio-mode-btn").removeClass("active");
      $(this).addClass("active");
      toggleControlPanel();
    });
    // Audio mode toggle (mini player bar)
    $(document).on("click", ".audio-mode-btn-mini", function(e) {
      e.stopPropagation();
      var mode = $(this).data("mode");
      $.get("/audio_mode/" + mode);
      $(".audio-mode-btn-mini").removeClass("active");
      $(this).addClass("active");
    });
```

with:

```javascript
    // Audio mode toggle (control panel)
    $(document).off("click.qv", ".audio-mode-btn").on("click.qv", ".audio-mode-btn", function() {
      var mode = $(this).data("mode");
      $.get("/audio_mode/" + mode);
      $(".audio-mode-btn").removeClass("active");
      $(this).addClass("active");
      toggleControlPanel();
    });
    // Audio mode toggle (mini player bar)
    $(document).off("click.qv", ".audio-mode-btn-mini").on("click.qv", ".audio-mode-btn-mini", function(e) {
      e.stopPropagation();
      var mode = $(this).data("mode");
      $.get("/audio_mode/" + mode);
      $(".audio-mode-btn-mini").removeClass("active");
      $(this).addClass("active");
    });
```

- [ ] **Step 5: Convert the admin keydown handler to namespaced off+on**

Replace:

```javascript
    $(document).keydown(function(e) {
```

with:

```javascript
    $(document).off("keydown.qv").on("keydown.qv", function(e) {
```

(Leave the handler body and the closing `});` unchanged.)

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run --no-sync pytest tests/unit/test_queueview_idempotent_handlers.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full suite + lint gate**

Run: `uv run --no-sync pytest tests/ -q`
Expected: all green (one new test added).
Run: `uv run pre-commit run --config code_quality/.pre-commit-config.yaml --all-files`
Expected: clean (Black/isort/pylint/mdformat all pass).

**Manual test checklist (Task 1):**
- Open `/queue` on the phone remote, navigate away to `/songpicker` and back ~3 times via in-app links (SPA nav), then tap a queued song's cog → the options modal opens once (not stacked); pick "上移" → the song moves exactly one position (not N).
- Tap a 原唱/伴奏 button after several back-and-forth navigations → audio mode switches once; the control-panel drawer does NOT toggle.
- (admin) Press the spacebar after several navigations → playback pauses once.

- [ ] **Step 8: Commit**

```bash
git add tests/unit/test_queueview_idempotent_handlers.py pikaraoke/templates/queueview.html
git commit -m "fix: make queueview document-delegated handlers idempotent across SPA nav"
```

---

### Task 2: Migrate queueview now-playing to nowPlayingStore

**Problem:** `queuePage_getQueue` fetches `/get_queue` AND `/now_playing` together (`$.when(...)`), parses now-playing itself, and queueview separately binds `socket.on("now_playing", queuePage_getQueue)`. This is the third duplicate now-playing parse that `nowPlayingStore` exists to remove (songpicker and the splash mini-strip already migrated). After this task the store owns the `now_playing` socket subscription and the `/now_playing` fetch; queueview subscribes and renders.

**Files:**
- Modify: `pikaraoke/templates/queueview.html`
- Test: `tests/unit/test_queueview_uses_store.py`

**Interfaces:**
- Consumes (already on `window`, bootstrapped in `base.html`): `window.nowPlayingStore.subscribe(key, cb)`, global `isEqual(a, b)`, global `getSemitonesLabel(n)`.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_queueview_uses_store.py`:

```python
import os

_QV = os.path.join(
    os.path.dirname(__file__), "..", "..", "pikaraoke", "templates", "queueview.html"
)


def _read():
    with open(_QV, encoding="utf-8") as f:
        return f.read()


def test_queueview_subscribes_to_store():
    html = _read()
    assert 'window.nowPlayingStore.subscribe("queueview", onNowPlaying);' in html


def test_queueview_no_longer_fetches_or_binds_now_playing_itself():
    html = _read()
    # The store owns the now_playing socket subscription now.
    assert 'window.socket.on("now_playing", window.queuePage_getQueue)' not in html
    # queuePage_getQueue must not fetch /now_playing anymore (queue-only).
    assert "now_playing.now_playing" not in html
    assert "$.when(" not in html


def test_queueview_shares_one_render_function():
    html = _read()
    # Queue-update path and store callback both go through the extracted renderer.
    assert "function rerenderQueueList()" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_queueview_uses_store.py -v`
Expected: FAIL (none of these strings exist yet).

- [ ] **Step 3: Extract the queue-list renderer and make queuePage_getQueue queue-only**

Replace the whole `window.queuePage_getQueue = function() { ... };` block (the one using `$.when($.get(get_queue), $.get(now_playing))`) with the following two functions:

```javascript
  // Re-render the queue list from current cached state (queue + now-playing).
  // Shared by the queue-update fetch and the now-playing store callback.
  function rerenderQueueList() {
    var table = document.getElementById('queue-list');
    if (table && table.sortableInstance) {
      table.sortableInstance.destroy();
      table.sortableInstance = null;
    }
    $("#queue-list").html(generateQueueHTML());
    window.initSortable();
    if (window.highlightAfterRefresh) {
      var fileToHighlight = window.highlightAfterRefresh;
      window.highlightAfterRefresh = null;
      $('.queue-song-options-btn').each(function() {
        if (decodeURIComponent($(this).data('file')) === fileToHighlight) {
          $(this).closest('.queue-item').addClass('row-moved');
        }
      });
    }
  }

  // Queue-only fetch. Now-playing arrives via the nowPlayingStore subscription.
  window.queuePage_getQueue = function() {
    if ($('#queue-list').length === 0) return;
    $.get('{{ url_for("queue.get_queue") }}', function(queueResp) {
      var newQueue = JSON.parse(queueResp);
      if (isEqual(newQueue, window.queuePageState.previousQueue)) return;
      window.queuePageState.queue = newQueue;
      window.queuePageState.previousQueue = newQueue;
      rerenderQueueList();
    });
  };

  // Now-playing changes drive the mini player and the now-playing row in the list.
  function onNowPlaying(np) {
    if (isEqual(np, window.queuePageState.previousNowPlaying)) return;
    window.queuePageState.nowPlaying = np;
    window.queuePageState.previousNowPlaying = np;
    updateMiniPlayer(np);
    rerenderQueueList();
  }
```

Notes for the implementer:
- `generateQueueHTML`, `updateMiniPlayer`, `initSortable`, `updateFairQueueCounts` are unchanged and still read `window.queuePageState.queue` / `.nowPlaying`.
- The `onEnd` sortable reorder handler already sets `window.queuePageState.previousQueue = null;` then calls `window.queuePage_getQueue()` — that still forces a queue refetch+render. Leave it as is.

- [ ] **Step 4: Remove queueview's own now_playing socket binding and subscribe to the store**

Find the socket-listeners block. Replace the now_playing binding line:

```javascript
  window.socket.off("now_playing"); window.socket.on("now_playing", window.queuePage_getQueue);
```

with:

```javascript
  window.nowPlayingStore.subscribe("queueview", onNowPlaying);
```

Leave the `queue_update`, `download_started`, `download_stopped`, `separation_started`, `separation_complete`, and `processing_progress` bindings exactly as they are.

- [ ] **Step 5: Run the new test to verify it passes**

Run: `uv run --no-sync pytest tests/unit/test_queueview_uses_store.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the full suite + lint gate**

Run: `uv run --no-sync pytest tests/ -q`
Expected: all green.
Run: `uv run pre-commit run --config code_quality/.pre-commit-config.yaml --all-files`
Expected: clean.

**Manual test checklist (Task 2):**
- Load `/queue` while a song is playing → mini player shows title/singer; the queue list shows the now-playing row on top followed by the queued songs; sortable still works for queued (non-now-playing) rows.
- Skip to the next song from another device → the mini player and the now-playing row both update within a second (store-driven), without a full-page reload.
- Add/remove/reorder a queued song from another device → the queue list updates (queue_update path); the now-playing row is unaffected.
- Open the control-panel drawer → song/singer, volume, transpose label, and audio-mode active state reflect the current now-playing.
- Empty-queue + nothing playing → the "目前沒有排隊的歌曲 / 去點歌" empty state shows.
- Known, acceptable (same as songpicker slice-2 Minor A): on first load the queue and now-playing arrive via two independent async paths, so there can be a brief frame rendered with only one of them before the other fills in; it self-corrects on the next render. Do not add coordination for this.

- [ ] **Step 7: Commit**

```bash
git add tests/unit/test_queueview_uses_store.py pikaraoke/templates/queueview.html
git commit -m "refactor: use nowPlayingStore in queueview, dropping its duplicate now-playing fetch"
```

---

## Self-Review

- **Spec coverage:** Design §5.4 (`nowPlayingStore` as single source of truth, "消滅三份重複的 now-playing 解析") — songpicker + splash mini-strip done; this plan removes the third (queueview). Design §5.3 lists queueview's eventual module split; the memory's remaining-work note pairs the store migration with the delegated-handler idempotency bug — Task 1 covers that bug, Task 2 the store migration. Full module split (now-playing-bar / controls / queue-view as separate ES modules) is explicitly NOT in this slice; it stays a later phase.
- **Placeholder scan:** none — every step shows the exact code.
- **Type/name consistency:** `rerenderQueueList`, `onNowPlaying`, `queuePage_getQueue`, `window.queuePageState.{queue,previousQueue,nowPlaying,previousNowPlaying}`, `isEqual`, `generateQueueHTML`, `updateMiniPlayer`, `initSortable` are used consistently and all pre-exist except the two new functions defined here. Subscribe key `"queueview"` is distinct from songpicker's `"songpicker-mini"` and splash's keys.
- **Risk:** Task 2 changes the render flow. Mitigation: behavior-preserving diff (`isEqual` guards both paths, mirroring the prior combined-diff), and the queue-list renderer is the same `generateQueueHTML` output as before. Manual checklist covers skip/reorder/drawer/empty.
