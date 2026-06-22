# KTV Frontend Refactor — Phase 2b (slice 1): Legacy Page Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the two orphaned legacy pages (`files.html`, `search.html`) and their `_legacy` route functions, so `songpicker.html` (browse/search) and `queueview.html` (queue) are unambiguously the live pages.

**Architecture:** `/browse` and `/search` already 302-redirect to `/songpicker` (the live page); `/browse_legacy` and `/search_legacy` are reachable only by typing those URLs (verified: zero `url_for`/template/JS/nav references). Removing the `_legacy` route functions + their templates is safe cleanup. The `pycln` pre-commit hook auto-removes the now-unused imports.

**Tech Stack:** Flask/Jinja2, pytest. Lint via pre-commit (pycln/black/isort/pylint).

## Global Constraints

- **Branch:** all work stays on `refactor/ktv-frontend`. NEVER commit to `master`/`main`. New commit per task (no amend).
- **Test command:** `uv run --no-sync pytest tests/ -q` (currently 767 passing) or per-file. `--no-sync` required.
- **Lint/import-cleanup:** after deleting a route, run `uv run pre-commit run --config code_quality/.pre-commit-config.yaml --files <changed files>` — `pycln` removes now-unused imports automatically; commit the result. (pre-commit also runs black/isort/pylint.)
- **Commits:** Conventional Commits (`refactor:` for these removals; header ≤150 chars). No emoji.
- **DO NOT DELETE the shared helpers** `_detect_language` and `_extract_artist` (defined in `pikaraoke/routes/files.py:26,37`). They are imported and used by the LIVE code: `songpicker.py:16`, `karaoke.py:307`, `download_manager.py:362`. Only the `browse_legacy` route function is removed from `files.py`.
- **KEEP the live redirect routes** `/browse` (files.py:58-65) and `/search` (search.py:41-45) — only the `_legacy` variants are removed.
- **No behavior change for live pages.** The live `/songpicker`, `/queue` are untouched.
- **Known deferred regression:** the duet / 2nd-singer input (`#duet-singer-2`) lived ONLY in the orphaned `search.html`. Since `/search_legacy` is unreachable from the UI, duet *entry* is already practically unavailable; deleting it loses no reachable feature. Re-introducing duet entry into `songpicker.html` is a separate deferred feature (see the Deferred section). The reference snippet is preserved in the Phase-1 plan's Deferred Appendix.

---

## Task Overview

| # | Task | Risk |
|---|------|------|
| 1 | Remove `browse_legacy` route + `files.html` | low |
| 2 | Remove `search_legacy` route + `search.html` | low |

---

### Task 1: Remove the `browse_legacy` route and `files.html`

**Files:**
- Modify: `pikaraoke/routes/files.py` (delete the `browse_legacy` function, lines 68-171; KEEP `_detect_language`/`_extract_artist` and the `/browse` redirect)
- Delete: `pikaraoke/templates/files.html`
- Test: `tests/unit/test_legacy_removed.py` (new)

**Interfaces:** none produced. `/browse` redirect and the shared helpers are unchanged.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_legacy_removed.py`. It uses the `full_client` fixture from `test_new_features.py` only if importable; instead, to stay self-contained, build a minimal app that registers the blueprints needed for the `/browse` redirect (`files_bp` + `songpicker_bp`, since the redirect targets `songpicker.songpicker`):

```python
import os

import pytest
import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from pikaraoke.routes.files import files_bp
from pikaraoke.routes.songpicker import songpicker_bp

_TEMPLATE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "pikaraoke", "templates"
)


@pytest.fixture
def app():
    test_app = Flask(__name__)
    test_app.register_blueprint(files_bp)
    test_app.register_blueprint(songpicker_bp)
    return test_app


@pytest.fixture
def client(app):
    return app.test_client()


def test_files_legacy_template_removed():
    """files.html was the orphaned /browse_legacy page — must be gone."""
    assert not os.path.exists(os.path.join(_TEMPLATE_DIR, "files.html"))


def test_browse_still_redirects_to_songpicker(client):
    """The live /browse entry must still 302-redirect (proves files.py intact)."""
    resp = client.get("/browse")
    assert resp.status_code == 302
    assert "/songpicker" in resp.headers["Location"]


def test_browse_legacy_route_removed(client):
    """/browse_legacy must no longer exist."""
    assert client.get("/browse_legacy").status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --no-sync pytest tests/unit/test_legacy_removed.py -q`
Expected: FAIL — `files.html` still exists; `/browse_legacy` still resolves (not 404).

- [ ] **Step 3: Delete the `browse_legacy` function and the template**

In `pikaraoke/routes/files.py`, delete the entire `browse_legacy` view function (the `@files_bp.route("/browse_legacy", ...)` decorator and its `def browse_legacy(): ...` body, lines 68-171). Do NOT touch `_detect_language` (line 26), `_extract_artist` (line 37), the `/browse` redirect (lines 58-65), or any other function. Then delete the template:

```bash
git rm pikaraoke/templates/files.html
```

- [ ] **Step 4: Auto-clean now-unused imports**

Run pre-commit on the changed Python file so `pycln` removes imports that only `browse_legacy` used (e.g. `Pagination`, `get_page_parameter`, possibly `unicodedata`/`unquote`/`Counter` if unused elsewhere):

Run: `uv run pre-commit run --config code_quality/.pre-commit-config.yaml --files pikaraoke/routes/files.py`
Expected: hooks pass (pycln may modify the file — that is intended; re-stage it). If pylint reports a genuinely-unused module-level helper that grep confirms is browse_legacy-only, remove it too; but `_detect_language`/`_extract_artist` are shared and MUST remain.

- [ ] **Step 5: Run the tests, then the full suite**

Run: `uv run --no-sync pytest tests/unit/test_legacy_removed.py -q`
Expected: PASS.
Run: `uv run --no-sync pytest tests/ -q`
Expected: PASS (suite green; no test referenced files.html / browse_legacy).

- [ ] **Step 6: Commit**

```bash
git add pikaraoke/routes/files.py tests/unit/test_legacy_removed.py
git commit -m "refactor: remove orphaned browse_legacy route and files.html"
```

---

### Task 2: Remove the `search_legacy` route and `search.html`

**Files:**
- Modify: `pikaraoke/routes/search.py` (delete the `search_legacy` function, ~lines 48-70; KEEP the `/search` redirect at lines 41-45)
- Delete: `pikaraoke/templates/search.html`
- Test: `tests/unit/test_legacy_removed.py` (add assertions)

**Interfaces:** none produced. `/search` redirect unchanged.

- [ ] **Step 1: Add the failing assertions**

Append to `tests/unit/test_legacy_removed.py` (the `search_bp` provides `/search` and previously `/search_legacy`):

```python
from pikaraoke.routes.search import search_bp


@pytest.fixture
def search_app():
    test_app = Flask(__name__)
    test_app.register_blueprint(search_bp)
    test_app.register_blueprint(songpicker_bp)
    return test_app


@pytest.fixture
def search_client(search_app):
    return search_app.test_client()


def test_search_legacy_template_removed():
    """search.html was the orphaned /search_legacy page — must be gone."""
    assert not os.path.exists(os.path.join(_TEMPLATE_DIR, "search.html"))


def test_search_still_redirects_to_songpicker(search_client):
    resp = search_client.get("/search")
    assert resp.status_code == 302
    assert "/songpicker" in resp.headers["Location"]


def test_search_legacy_route_removed(search_client):
    assert search_client.get("/search_legacy").status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --no-sync pytest tests/unit/test_legacy_removed.py -q`
Expected: FAIL on the three new assertions (search.html exists; /search_legacy resolves).

- [ ] **Step 3: Delete the `search_legacy` function and the template**

In `pikaraoke/routes/search.py`, delete the entire `@search_bp.route("/search_legacy", ...)` view function (`def search_legacy(): ...`, ~lines 48-70). Do NOT touch the `/search` redirect (lines 41-45). Then:

```bash
git rm pikaraoke/templates/search.html
```

- [ ] **Step 4: Auto-clean now-unused imports**

Run: `uv run pre-commit run --config code_quality/.pre-commit-config.yaml --files pikaraoke/routes/search.py`
Expected: hooks pass; `pycln` removes any imports only `search_legacy` used. Re-stage if modified.

- [ ] **Step 5: Run the tests, then the full suite**

Run: `uv run --no-sync pytest tests/unit/test_legacy_removed.py -q`
Expected: PASS (all six assertions).
Run: `uv run --no-sync pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pikaraoke/routes/search.py tests/unit/test_legacy_removed.py
git commit -m "refactor: remove orphaned search_legacy route and search.html"
```

---

## Phase 2b (slice 1) Done — Definition

- `uv run --no-sync pytest tests/ -q` green (767 baseline + the new legacy-removal tests).
- `files.html` and `search.html` are deleted; `/browse_legacy` and `/search_legacy` return 404; `/browse` and `/search` still redirect to `/songpicker`.
- The shared helpers `_detect_language`/`_extract_artist` remain and live code still imports them.
- pre-commit (pycln/black/isort/pylint) passes on the changed route files.

## Deferred (later slices)
- **Duet / 2nd-singer entry in songpicker** — re-introduce as a NEW feature (songpicker enqueues via per-song GET links, unlike search.html's form, so this needs a small UX design: an optional "duet partner" field that the enqueue carries as `song_added_by_2`). Reference markup preserved in the Phase-1 plan's Deferred Appendix.
- `core/nowPlayingStore` (centralize the duplicated `/now_playing` fetch/parse across queueview/songpicker); bottom-tab IA (點歌/排隊/計分/更多); splash modularization (Phase 3).
