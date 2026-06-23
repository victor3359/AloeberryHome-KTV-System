# Splash Modularization Slice 2 — Lock in the module boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add durable, generic guard tests that lock in the splash ES-module boundary's safety invariants, so the later extraction slices (3-9) cannot silently re-break it — without changing any runtime code.

**Architecture:** Slice 1 made `splash.js` an ES module and already neutralized the two real breakages (`window.handleConfirmation`, `window.scoreReviews`). A controller audit (2026-06-24) proved the boundary is currently complete and safe: the only inline HTML handlers are two `handleConfirmation()` calls (window-exposed); the only classic-helper→splash read is `score.js` reading `window.scoreReviews`; `pitch-analyzer/meter.js` only window-attach their own classes (splash reads them bare, safe in module scope); no inline `<script>` calls a splash function at parse time. This slice converts those one-time audit facts into **generic, self-maintaining tests** so any future slice that adds an inline handler without a window binding, or drops a needed window exposure, fails CI. Pure test additions — no source change.

**Tech Stack:** Python string-assertion tests over template/JS files (repo convention; no JS harness, zero build).

## Global Constraints

- **Test-only slice.** No change to `splash.js`, `splash.html`, `screensaver.js`, `score.js`, or any runtime file. If a test reveals a real gap, STOP and report it (do not silently fix runtime code under a test-only slice).
- The boundary facts being locked (verified by audit): inline handlers in `splash.html` are exactly the two `onClick="handleConfirmation()"`; `window.handleConfirmation` and `window.scoreReviews` are the splash exposures used for HTML/classic-helper interop; the screensaver import specifier is `/static/screensaver.js`.
- No framework, no build step, zh-TW. Tests must be deterministic and not depend on a running server.
- Quality gate before done: `uv run --no-sync pytest tests/ -q` green AND `uv run pre-commit run --config code_quality/.pre-commit-config.yaml --all-files` clean (drop unrelated `--all-files` formatter churn with `git checkout -- .`, keeping only the new test file).

---

### Task 1: Add module-boundary invariant guard tests

**Files:**
- Test: `tests/unit/test_splash_module_boundary.py` (new)

**Interfaces:**
- Consumes: the slice-1 facts — `splash.js` is a module; inline handlers call `handleConfirmation`; `window.handleConfirmation` / `window.scoreReviews` exist; import is `/static/screensaver.js`.
- Produces: nothing other tasks depend on (pure guard).

- [ ] **Step 1: Write the tests (they should pass immediately — they encode the current, audited-safe state; this is a guard, not RED→GREEN)**

Create `tests/unit/test_splash_module_boundary.py`:

```python
import os
import re

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_SPLASH_JS = os.path.join(_PKG, "static", "js", "splash.js")
_SPLASH_HTML = os.path.join(_PKG, "templates", "splash.html")
_SCORE = os.path.join(_PKG, "static", "score.js")
_FIREWORKS = os.path.join(_PKG, "static", "fireworks.js")
_PITCH_ANALYZER = os.path.join(_PKG, "static", "js", "pitch-analyzer.js")
_PITCH_METER = os.path.join(_PKG, "static", "js", "pitch-meter.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_every_inline_handler_in_splash_html_is_window_exposed():
    """splash.js is an ES module: its top-level functions are NOT auto-attached to window, so
    any inline on*= handler in splash.html must call a function explicitly assigned to window
    (e.g. `window.handleConfirmation = ...`). This generic guard fails the moment a future slice
    adds an inline handler without the matching window binding, or removes a needed binding."""
    html = _read(_SPLASH_HTML)
    js = _read(_SPLASH_JS)
    # Extract the called function name from each on*="fn(...)" attribute.
    handlers = re.findall(r"on[A-Za-z]+=[\"']\s*([A-Za-z_$][\w$]*)\s*\(", html)
    assert handlers, "expected at least one inline handler in splash.html to guard"
    for fn in sorted(set(handlers)):
        assert re.search(rf"window\.{re.escape(fn)}\s*=", js), (
            f"inline handler {fn}() in splash.html is not exposed via `window.{fn} =` in splash.js "
            f"-> it would throw under ES-module scope"
        )


def test_no_classic_helper_reads_a_bare_splash_global():
    """The only state crossing from a classic helper into splash is score.js reading the score
    phrases. It must go through window.scoreReviews (slice 1), never a bare global, because a
    bare read cannot see splash.js's module-scoped bindings. Guards every classic helper that
    runs alongside the splash module."""
    score = _read(_SCORE)
    fireworks = _read(_FIREWORKS)
    # score.js reads/writes only window.scoreReviews, never bare scoreReviews.
    assert "window.scoreReviews" in score
    assert re.search(r"(?<!window\.)\bscoreReviews\b", score) is None
    # fireworks.js touches no splash-owned global (only browser globals like window.innerWidth).
    assert re.search(r"(?<!window\.)\bscoreReviews\b", fireworks) is None


def test_pitch_helpers_only_window_attach_their_classes():
    """pitch-analyzer.js / pitch-meter.js publish their classes on window; splash reads them as
    bare names, which resolves in module scope because window properties are global. Lock this
    direction so a future slice converting these to ES modules removes the window leak knowingly."""
    pa = _read(_PITCH_ANALYZER)
    pm = _read(_PITCH_METER)
    assert "window.PitchAnalyzer" in pa
    assert "window.PitchMeter" in pm


def test_screensaver_import_specifier_is_the_static_path():
    """The screensaver import uses the absolute static path (Flask serves /static by default;
    there is no custom static_url_path). Pin it so a path/serving change fails loudly here rather
    than at runtime on the TV."""
    js = _read(_SPLASH_JS)
    assert 'from "/static/screensaver.js"' in js
```

- [ ] **Step 2: Run the new tests — confirm they pass against the current tree**

Run: `uv run --no-sync pytest tests/unit/test_splash_module_boundary.py -v`
Expected: PASS (4 tests). These encode the audited-safe current state. **If any FAILS, STOP and report** — it means the audit missed a real gap and this should not be a test-only slice.

- [ ] **Step 3: Sanity-check the guard actually bites (temporary mutation, then revert)**

To prove `test_every_inline_handler_in_splash_html_is_window_exposed` is load-bearing (not vacuously passing), temporarily verify by reasoning or a throwaway local check that removing `window.handleConfirmation = handleConfirmation;` from splash.js would fail it. Do NOT commit any such mutation — this is a thinking step to confirm the regex captures `handleConfirmation` and the window-assignment lookup matches `window.handleConfirmation =`. (The two `onClick="handleConfirmation()"` attributes yield `handlers == ["handleConfirmation", "handleConfirmation"]`; `window.handleConfirmation =` is present at splash.js:124.)

- [ ] **Step 4: Run the full suite + lint gate**

Run: `uv run --no-sync pytest tests/ -q` → all green (4 new tests).
Run: `uv run pre-commit run --config code_quality/.pre-commit-config.yaml --all-files` → clean. Drop unrelated formatter churn with `git checkout -- .` (keep only the new test file).

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_splash_module_boundary.py
git commit -m "test: lock in splash ES-module boundary invariants (inline handlers, cross-file globals)"
```

---

## Self-Review

- **Spec coverage:** Implements the analysis-doc slice 2 ("harden the module-conversion surface") as a generic, self-maintaining guard rather than a one-time audit. The four tests lock: (1) every inline handler is window-exposed (protects slices 3-9 that touch the boot surface); (2) no classic helper reads a bare splash global (the `scoreReviews` invariant, generalized); (3) the pitch-helper window-attach direction (so slice 4's conversion is deliberate); (4) the import specifier (the reviewer's M2-adjacent hardening rec).
- **Placeholder scan:** none — full test code given.
- **Type/name consistency:** regex `window\.{fn}\s*=` matches the `window.handleConfirmation = ...` form from slice 1; the `(?<!window\.)\bscoreReviews\b` negative-lookbehind matches the slice-1 Task-1 test's proven form.
- **Scope discipline:** test-only; if a guard fails, that is a real finding to escalate, not a license to edit runtime code in this slice.
