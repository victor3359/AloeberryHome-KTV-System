# KTV Frontend Refactor — Phase 4a: Reset/New-Session + Favorites — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface two backend-complete features that currently have NO UI: (1) the session reset / "開新一夜" action (which also makes the already-wired splash session-summary screen reachable), and (2) per-song Favorites on the browse cards.

**Architecture:** Pure additive frontend wiring to existing backend routes — no server/route changes. The reset action is `GET /reset_session` (`url_for('admin.reset_session')`, admin-gated server-side, destructive, emits the `session_summary` socket event the splash already renders). Favorites uses `POST /favorites/toggle {user, filename}` and the `user_favorites` set `songpicker.py` already passes to its template.

**Tech Stack:** Flask/Jinja2 templates, jQuery (classic, global), `Cookies`/`showNotification`/`window.getSocket` globals. Tests: pytest (full_client render + content assertions). No JS test runner.

## Global Constraints

- **Branch:** all work stays on `refactor/ktv-frontend`. NEVER commit to `master`/`main`. New commit per task (no amend).
- **Test command:** `uv run --no-sync pytest tests/ -q` (currently 763 passing) or per-file. `--no-sync` required.
- **No JS/CSS/HTML linter** — new JS/markup is manual-review only. Lint Python with `uv run pre-commit run --config code_quality/.pre-commit-config.yaml --all-files`.
- **Commits:** Conventional Commits (`feat|fix|refactor|...`; header ≤150 chars).
- **No emoji / unicode emoji substitutes.** The icon font (`fontello.css`) has NO heart/star glyph — Favorites uses a **text-label pill** ("收藏"/"已收藏") reusing the existing `.sp-pill`/`.sp-pill--active` classes. The reset button uses the existing `icon-exchange` glyph.
- **UI strings:** Traditional Chinese (zh-TW), inline (single-language).
- **No server change:** these routes already exist and are registered. Do not modify `admin.py`, `scores.py`, `karaoke.py`, `lib/favorites.py`, or `splash.js` (the splash already renders `session_summary`).
- **Key-matching invariant (favorites):** the heart MUST POST the full `song` path (the Jinja loop var `song`) as `filename` — `user_favorites` is a set of full paths and `Favorites` keys by exact string. Never post `filename_from_path(song)`/display title.
- **Manual smoke deferred to the human controller** (no JS runner): the automated tests assert wiring; behavior (button fires reset → splash summary shows; heart toggles + persists) is the controller's check.

---

## Task Overview

| # | Task | Risk |
|---|------|------|
| 1 | "開新一夜" reset button on the live control page (`queueview.html`) + confirm | low |
| 2 | Favorites text-pill toggle on `songpicker.html` browse cards | low-medium |

> **Scope note:** the reset entry is added to the live control page only (most discoverable for the host mid-night); an `info.html` duplicate and the search-results heart are deferred. Transpose-persistence, recommendations, most-played, and reprocess UIs are separate later slices.

---

### Task 1: "開新一夜" reset button on the live control page

`GET /reset_session` is fully implemented (computes the summary, emits `session_summary` to the splash if any songs were played, then clears queue/scores/history/timer and redirects to `/queue`) but has no UI. Add an admin-gated, confirm-guarded button to the live control page's Queue-actions row.

**Files:**
- Modify: `pikaraoke/templates/queueview.html` (button in the `{% if admin %}` Queue-actions row at lines 466-478; confirm handler in the inline `<script>`)
- Test: `tests/unit/test_new_features.py` (add two methods to the existing `TestKeyboardShortcuts` class, reusing its `_make_mock_karaoke` + the module's `full_client` fixture)

**Interfaces:**
- Consumes: `url_for('admin.reset_session')`; the splash's existing `session_summary` socket handler (no change).

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_new_features.py`, add these two methods inside the existing `class TestKeyboardShortcuts` (it already defines `_make_mock_karaoke` and the module defines the `full_client` fixture and patches `pikaraoke.routes.queue.{get_karaoke_instance,get_site_name,is_admin}`):

```python
    @patch("pikaraoke.routes.queue.get_karaoke_instance")
    @patch("pikaraoke.routes.queue.get_site_name", return_value="Test")
    @patch("pikaraoke.routes.queue.is_admin", return_value=True)
    def test_admin_sees_new_session_button(self, _admin, _site, mock_k, full_client):
        mock_k.return_value = self._make_mock_karaoke()
        html = full_client.get("/queue").data.decode()
        assert "confirm-new-session" in html
        assert "/reset_session" in html

    @patch("pikaraoke.routes.queue.get_karaoke_instance")
    @patch("pikaraoke.routes.queue.get_site_name", return_value="Test")
    @patch("pikaraoke.routes.queue.is_admin", return_value=False)
    def test_non_admin_no_new_session_button(self, _admin, _site, mock_k, full_client):
        mock_k.return_value = self._make_mock_karaoke()
        html = full_client.get("/queue").data.decode()
        assert "confirm-new-session" not in html
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --no-sync pytest "tests/unit/test_new_features.py::TestKeyboardShortcuts::test_admin_sees_new_session_button" -q`
Expected: FAIL (no `confirm-new-session`/`/reset_session` in the rendered queue page yet).

- [ ] **Step 3: Add the button to the Queue-actions row**

In `pikaraoke/templates/queueview.html`, inside the `{% if admin %}` Queue-actions `<div>` (lines 466-478), add the reset button after the existing 清除 (clear) link, so the row ends:

```html
  <a class="pill" style="border:1px solid var(--danger); color:var(--danger)" href="/queue/edit?action=clear">
    <i class="icon icon-trash-empty"></i> 清除
  </a>
  <a class="pill confirm-new-session" style="border:1px solid var(--warning); color:var(--warning)" href="{{ url_for('admin.reset_session') }}">
    <i class="icon icon-exchange"></i> 開新一夜
  </a>
```

- [ ] **Step 4: Add the confirm handler to the inline script**

In `queueview.html`'s inline `<script>` (the same block that holds the socket listeners), add a delegated, idempotent confirm handler (idempotent `off().on()` because this script re-runs on SPA navigation). Place it near the other handlers, e.g. just before the `// Socket listeners` comment (around line 299):

```javascript
  // Confirm before starting a new session (clears queue, scores, and history)
  $(document).off("click", ".confirm-new-session").on("click", ".confirm-new-session", function (e) {
    e.preventDefault();
    if (window.confirm("確定要開始新場次嗎？目前佇列、分數與歷史將被清除。")) {
      window.location.href = this.href;
    }
  });
```

- [ ] **Step 5: Run the tests, then the full suite**

Run: `uv run --no-sync pytest "tests/unit/test_new_features.py::TestKeyboardShortcuts" -q`
Expected: PASS (both new tests + the existing class tests).
Run: `uv run --no-sync pytest tests/ -q`
Expected: PASS (suite green).

- [ ] **Step 6: Manual smoke (deferred to human controller)**

Note in the report that the controller should verify: on `/queue` as admin, the "開新一夜" button appears; clicking it prompts a confirm; confirming navigates to `/queue` and (if songs were played this session) the `/splash` screen shows the session-summary overlay, then the queue/scores are cleared.

- [ ] **Step 7: Commit**

```bash
git add pikaraoke/templates/queueview.html tests/unit/test_new_features.py
git commit -m "feat: add open-new-session reset button to the control page"
```

---

### Task 2: Favorites text-pill toggle on the browse cards

`POST /favorites/toggle {user, filename}` and `songpicker.py`'s `user_favorites` set are fully implemented but unconsumed. Add a per-card "收藏"/"已收藏" toggle to the browse song cards.

**Files:**
- Modify: `pikaraoke/templates/songpicker.html` (browse-card markup at the `{% for song in available_songs %}` loop ~472-502; a delegated click handler in the inline `$(function(){...})` script)
- Test: `tests/unit/test_favorites_ui.py` (new — content assertions)

**Interfaces:**
- Consumes: `url_for('scores.toggle_favorite')` (→ `/favorites/toggle`); the `user_favorites` set already passed by `songpicker.py`; globals `setUserCookie()`, `Cookies`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_favorites_ui.py` (content assertions, mirroring the project's `test_module_bootstrap.py` style):

```python
import os

_SONGPICKER = os.path.join(
    os.path.dirname(__file__), "..", "..", "pikaraoke", "templates", "songpicker.html"
)


def _read():
    with open(_SONGPICKER, encoding="utf-8") as f:
        return f.read()


def test_browse_card_has_favorite_toggle_markup():
    html = _read()
    assert "sp-fav-toggle" in html
    assert 'data-song="{{ song }}"' in html
    assert "{% if song in user_favorites %}" in html


def test_favorite_toggle_posts_full_song_path_to_route():
    html = _read()
    assert "url_for('scores.toggle_favorite')" in html
    assert "filename: song" in html
    assert "已收藏" in html
    assert "收藏" in html
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --no-sync pytest tests/unit/test_favorites_ui.py -q`
Expected: FAIL (`songpicker.html` has no favorites markup yet).

- [ ] **Step 3: Add the favorite toggle to the browse card**

In `pikaraoke/templates/songpicker.html`, in the `{% for song in available_songs %}` loop, add the toggle as a sibling between the closing `</div>` of `.sp-song-card__info` and the `{% if song in queue_files %}` block. The card's tail becomes:

```html
      </div>
      <button type="button" class="sp-pill sp-fav-toggle{% if song in user_favorites %} sp-pill--active{% endif %}" data-song="{{ song }}">{% if song in user_favorites %}已收藏{% else %}收藏{% endif %}</button>
      {% if song in queue_files %}
        <span class="sp-song-card__queued"><i class="icon icon-ok"></i></span>
      {% else %}
        <a class="sp-song-card__action add-song-link"
           href="{{ url_for('queue.enqueue') }}?song={{ url_escape(song.encode('utf-8','surrogateescape')) }}&user="
           title="加入排隊"><i class="icon icon-plus"></i></a>
      {% endif %}
```

(The `.sp-pill`/`.sp-pill--active` classes already exist in the page's `<style>` block — no new CSS. `.sp-fav-toggle` is just a JS hook.)

- [ ] **Step 4: Add the delegated toggle handler**

In `songpicker.html`'s inline `$(function () { ... })` block (the same one holding the `a.add-song-link` handler ~171-188), add an idempotent delegated handler. It posts the FULL `song` path as `filename`:

```javascript
  // ----- Favorites toggle -----
  $(document).off("click", ".sp-fav-toggle").on("click", ".sp-fav-toggle", function () {
    var btn = this;
    setUserCookie();
    var user = Cookies.get("user");
    var song = $(btn).attr("data-song");
    $.ajax({
      url: "{{ url_for('scores.toggle_favorite') }}",
      type: "POST",
      contentType: "application/json",
      data: JSON.stringify({ user: user, filename: song }),
      success: function (resp) {
        if (resp && resp.ok) {
          if (resp.is_favorite) {
            $(btn).addClass("sp-pill--active").text("已收藏");
          } else {
            $(btn).removeClass("sp-pill--active").text("收藏");
          }
        }
      },
    });
  });
```

- [ ] **Step 5: Run the tests, then the full suite**

Run: `uv run --no-sync pytest tests/unit/test_favorites_ui.py -q`
Expected: PASS.
Run: `uv run --no-sync pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Manual smoke (deferred to human controller)**

Note in the report that the controller should verify: on `/songpicker` (browse mode) the "收藏" pill appears on each card; clicking it flips to "已收藏" and back; a favorited song still shows "已收藏" after a page reload (persisted server-side per the `user` cookie).

- [ ] **Step 7: Commit**

```bash
git add pikaraoke/templates/songpicker.html tests/unit/test_favorites_ui.py
git commit -m "feat: add favorites toggle to songpicker browse cards"
```

---

## Phase 4a Done — Definition

- `uv run --no-sync pytest tests/ -q` green (763 baseline + the new tests).
- The host can start a new session from `/queue` (admin, with confirm), which makes the splash session-summary reachable.
- Browse cards on `/songpicker` show a working 收藏/已收藏 toggle that round-trips to `/favorites/toggle` with the full song path.
- No server/route/splash code changed.

## Deferred (later slices)
- `info.html` duplicate "開新一夜" entry; the search-results-row heart.
- Favorites list/filter view (GET `/favorites`); recommendations ("猜你想唱"), most-played/artist directory, reprocess UI; cross-song transpose persistence.
