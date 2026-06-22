# pylint Hook Repair + the 2 Bugs It Was Hiding — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the project's pylint pre-commit gate actually run (it was neutered to a no-op), and fix the 2 real error-level bugs that running pylint surfaces — so the gate is meaningful and green.

**Background (verified):** The pylint hook was triple-broken: (1) pylint is not a project dependency; (2) `code_quality/.pylintrc`'s `init-hook` imports `find_pylintrc` from `pylint.config`, an API removed in modern pylint (crashes pylint on startup); (3) the pre-commit hook `entry` was overridden to `bash -c 'echo $PATH'`. Running pylint `errors-only` (per the rcfile) on the package surfaces exactly 3 findings: a real `TypeError` bug (`splash.py:86`), a dead-code/wrong-assignment bug (`file_resolver.py:128`), and a false positive (`karaoke.py:635` `auto_dj`, a dynamically-set preference attribute). With `auto_dj` added to `generated-members` and the optional AI deps in `ignored-modules`, only the 2 real bugs remain — fixing them yields 0 errors.

**Tech Stack:** Python, pylint (errors-only), pre-commit (run via `uv`), pytest.

## Global Constraints

- **Branch:** `refactor/ktv-frontend`. NEVER commit to `master`/`main`. New commit per task (no amend).
- **Test command:** `uv run --no-sync pytest tests/ -q` (currently 776 passing). `--no-sync` required.
- **pylint command (for verification):** `uv run --no-sync pylint --rcfile=code_quality/.pylintrc pikaraoke` — expected to print no error lines and exit 0 after Task 1 + Task 2.
- **Commits:** Conventional Commits. No emoji.
- **Order matters:** Task 1 (fix the bugs) must land before Task 2 enables the gate, or enabling pylint would fail on the 2 errors.

---

## Task Overview

| # | Task | Risk |
|---|------|------|
| 1 | Fix the 2 real bugs pylint found (`splash.py:86`, `file_resolver.py:128`) | low |
| 2 | Repair the pylint tooling (rcfile + dep + un-neuter hook) and verify it runs clean | low-medium |

---

### Task 1: Fix the 2 bugs pylint found

**Files:**
- Modify: `pikaraoke/routes/splash.py:86`
- Modify: `pikaraoke/lib/file_resolver.py:128`
- Test: `tests/unit/test_pylint_bugfixes.py` (new)

**Interfaces:** none changed (both are internal fixes).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_pylint_bugfixes.py` (content assertions guarding both fixes):

```python
import os

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_SPLASH = os.path.join(_PKG, "routes", "splash.py")
_RESOLVER = os.path.join(_PKG, "lib", "file_resolver.py")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_splash_passes_url_to_raspi_wifi_text():
    # get_raspi_wifi_text(url: str) requires a url; the caller must pass k.url
    src = _read(_SPLASH)
    assert "get_raspi_wifi_text(k.url)" in src
    assert "get_raspi_wifi_text()" not in src


def test_file_resolver_drops_dead_resolved_file_path_assignment():
    # resolved_file_path was written once and never read; process_file returns None
    src = _read(_RESOLVER)
    assert "self.resolved_file_path" not in src
    assert "self.process_file(file_path)" in src
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --no-sync pytest tests/unit/test_pylint_bugfixes.py -q`
Expected: FAIL (splash still calls `get_raspi_wifi_text()` with no arg; file_resolver still has `self.resolved_file_path = ...`).

- [ ] **Step 3: Fix the splash bug (E1120)**

In `pikaraoke/routes/splash.py`, line 86, pass the PiKaraoke URL (the route already has `k = get_karaoke_instance()` and renders `url=k.url`). Change:

```python
                text = get_raspi_wifi_text(k.url)
```

(was `text = get_raspi_wifi_text()`. `get_raspi_wifi_text(url: str)` uses `url.rpartition(':')[0]`; `text` is rendered as `hostap_info`, so this restores the raspiwifi-master display instead of raising `TypeError`.)

- [ ] **Step 4: Fix the file_resolver bug (E1111)**

In `pikaraoke/lib/file_resolver.py`, line 128, drop the dead assignment (`process_file` returns `None` and `self.resolved_file_path` is never read anywhere). Change:

```python
        self.process_file(file_path)
```

(was `self.resolved_file_path = self.process_file(file_path)`. `process_file` mutates `self` for its side effects; the `None` it returns was being stored in an attribute no code reads — removing the assignment fixes the assignment-from-no-return and deletes dead state per CLAUDE.md.)

- [ ] **Step 5: Run the tests, then the full suite**

Run: `uv run --no-sync pytest tests/unit/test_pylint_bugfixes.py -q`
Expected: PASS.
Run: `uv run --no-sync pytest tests/ -q`
Expected: PASS (suite green; `resolved_file_path` had no consumers, so nothing breaks).

- [ ] **Step 6: Commit**

```bash
git add pikaraoke/routes/splash.py pikaraoke/lib/file_resolver.py tests/unit/test_pylint_bugfixes.py
git commit -m "fix: pass url to get_raspi_wifi_text and drop dead resolved_file_path assignment"
```

---

### Task 2: Repair the pylint tooling and verify it runs clean

**Files:**
- Modify: `code_quality/.pylintrc` (init-hook, ignored-modules, generated-members)
- Modify: `pyproject.toml` (add pylint to the dev dependency groups)
- Modify: `code_quality/.pre-commit-config.yaml` (replace the neutered pylint hook with a working local hook)
- Test: `tests/unit/test_pylint_bugfixes.py` (add a config-assertion)

**Interfaces:** the pylint pre-commit hook now actually lints.

- [ ] **Step 1: Add the failing config-assertion test**

Append to `tests/unit/test_pylint_bugfixes.py`:

```python
_PRECOMMIT = os.path.join(
    os.path.dirname(__file__), "..", "..", "code_quality", ".pre-commit-config.yaml"
)


def test_pylint_hook_is_not_neutered():
    cfg = _read(_PRECOMMIT)
    assert "echo $PATH" not in cfg
    assert "pylint --rcfile=code_quality/.pylintrc" in cfg
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_pylint_bugfixes.py::test_pylint_hook_is_not_neutered -q`
Expected: FAIL (the hook still has `echo $PATH`).

- [ ] **Step 3: Fix `code_quality/.pylintrc`**

Make three edits:

1. Line 67 — replace the broken init-hook (it imports the removed `find_pylintrc`) with a disabled one:

```ini
#init-hook=
```

2. Line 63 — ignore the optional AI deps (they live in the `[ai]` extra and may be absent in the lint env, which would raise `import-error`):

```ini
ignored-modules=demucs,whisper,faster_whisper,torch,torchaudio,audio_separator
```

3. The `generated-members=` line (~552) — suppress the dynamic-preference false positive:

```ini
generated-members=auto_dj
```

- [ ] **Step 4: Add pylint to the dev dependency groups in `pyproject.toml`**

`pyproject.toml` lists test deps in three dev sections. Add `pylint` alongside `pytest` in each (mirror the existing entries):

- In `[project.optional-dependencies]` `dev` (next to `"pytest>=9.0.2",`): add `"pylint>=3.0.1",`
- In `[dependency-groups]` `dev` (next to `"pytest>=9.0.2",`): add `"pylint>=3.0.1",`
- In `[tool.poetry.group.dev.dependencies]`: add the pylint entry in that section's style (e.g. `pylint = ">=3.0.1"`).

Then install it into the env:

Run: `uv sync`
Expected: pylint is installed; `uv run --no-sync pylint --version` prints a version.

- [ ] **Step 5: Un-neuter the pre-commit pylint hook**

In `code_quality/.pre-commit-config.yaml`, replace the entire pylint hook block (the `- repo: https://github.com/PyCQA/pylint` ... block, currently lines 33-40) with a local hook that runs pylint in the project env:

```yaml
- repo: local
  hooks:
  - id: pylint
    name: Lint Python Code
    entry: uv run --no-sync pylint --rcfile=code_quality/.pylintrc
    language: system
    types: [python]
```

- [ ] **Step 6: Verify pylint runs clean, then run the hook + full suite**

Run: `uv run --no-sync pylint --rcfile=code_quality/.pylintrc pikaraoke`
Expected: no error lines, exit code 0 (the rcfile is `errors-only`; the 2 bugs are fixed in Task 1; `auto_dj` is suppressed; AI deps ignored). If any error appears, STOP and report it — do not suppress real findings.

Run: `uv run pre-commit run pylint --all-files`
Expected: the pylint hook PASSES (it now actually runs).

Run: `uv run --no-sync pytest tests/unit/test_pylint_bugfixes.py -q` and `uv run --no-sync pytest tests/ -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add code_quality/.pylintrc code_quality/.pre-commit-config.yaml pyproject.toml uv.lock tests/unit/test_pylint_bugfixes.py
git commit -m "build: re-enable pylint pre-commit hook (fix rcfile init-hook, add dep, run via uv)"
```

---

## Done — Definition

- `uv run --no-sync pylint --rcfile=code_quality/.pylintrc pikaraoke` exits 0 with no error lines.
- `uv run pre-commit run pylint --all-files` passes (the hook actually lints now).
- `uv run --no-sync pytest tests/ -q` green (776 baseline + the new bugfix/config tests).
- The 2 real bugs (`splash.py:86` TypeError, `file_resolver.py:128` dead assignment) are fixed.

## Note (out of scope)
- CI (`.github/workflows/ci.yml`) runs `pre-commit run --all-files`; for the new `uv run --no-sync pylint` hook to work there, CI must have the dev deps synced (pylint present) before pre-commit. If CI's pre-commit step doesn't already `uv sync` the dev group, that is a one-line CI follow-up — flag it, don't fix it here unless trivial.
