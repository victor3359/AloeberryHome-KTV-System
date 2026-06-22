# Dynamic-Subtitle Correctness Fixes (pure-logic, unit-testable) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the two highest-value, verified, unit-testable correctness bugs in the karaoke-subtitle generation that the AI-pipeline forensic found: (1) lyric lines silently VANISHING (negative-duration ASS Dialogue), and (2) valid repeated CHORUS / long lines being DELETED by the hallucination filter when running on aligned online lyrics.

**Architecture:** Both fixes are pure Python logic in `pikaraoke/lib/karaoke_subtitle.py` (+ a one-line call-site change in `pikaraoke/lib/vocal_separator.py`). No demucs/whisper needed — fully unit-testable via `generate_karaoke_ass` / `_filter_whisper_hallucinations` (the existing `tests/unit/test_karaoke_subtitle.py` imports both).

**Tech Stack:** Python, pytest. (The `[ai]` deps are NOT required for these tests.)

## Global Constraints

- **Branch:** `refactor/ktv-frontend`. NEVER commit to `master`/`main`. New commit per task (no amend).
- **Test command:** `uv run --no-sync pytest tests/ -q` (currently 780 passing). `--no-sync` required.
- **Commits:** Conventional Commits (`fix:`). No emoji.
- **pylint gate** is now live — keep the touched `.py` files error-clean (these are small logic edits).
- **Behavior preservation:** the RAW-Whisper filtering path must keep its existing dedup/long-line behavior (regression-guarded); only the ALIGNED-online-lyrics path changes.

## Out of scope (deferred, with reasons)
- **Resume desync** (`ffmpeg -ss` vs absolute ASS timestamps; needs a splash.js `octopus` time-offset) — a frontend/playback change that has no JS test runner and is only reproducible by switching audio mode on a *stem-less* song or via server `/transpose`; better done with the splash slice + manual verification.
- **`\kf` fill color direction** (`karaoke_subtitle.py:262` inverted vs docstring) — subjective (sung = bright cream is arguably preferable); leave to a design decision, don't silently flip.
- **The root-cause DTW alignment** (`lyrics_corrector.py:139-141`) — an algorithm change needing `[ai]` deps to validate end-to-end; a separate slice.

---

## Task Overview

| # | Task | Risk |
|---|------|------|
| 1 | Fix negative-duration "line vanishes" in the two-line layout | low |
| 2 | Stop deleting repeated chorus / long lines on the aligned-lyrics path | low |

---

### Task 1: Fix the negative-duration Active line (lines silently vanishing)

In the two-line layout, `actual_start = max(start, pos_free_at[my_y])` can exceed the line's own `end` (when its row is busy past this line's end), but the Dialogue is written with the un-clamped `end` → `Start > End` → libass renders zero frames → the whole lyric line disappears.

**Files:**
- Modify: `pikaraoke/lib/karaoke_subtitle.py` (the Active-line emission, ~lines 306-312)
- Test: `tests/unit/test_karaoke_subtitle.py` (add a test)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_karaoke_subtitle.py` (it already imports `generate_karaoke_ass`). Add `import re` at the top if not present, then:

```python
def _ass_seconds(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def test_no_negative_duration_active_lines_on_overlap():
    """A line whose row is still busy past its own end must NOT be emitted with
    Start>End (which libass renders for zero frames -> the line silently vanishes)."""
    segments = [
        # seg0 occupies row active_y for ~6s
        {"words": [{"word": c, "start": j * 0.6, "end": j * 0.6 + 0.6}
                   for j, c in enumerate("一二三四五六七八九十")]},
        {"words": [{"word": "甲", "start": 0.1, "end": 0.4}]},
        # seg2 lands on the same row (active_y) but is short + early -> used to get Start>End
        {"words": [{"word": "乙", "start": 0.2, "end": 0.5}]},
    ]
    ass = generate_karaoke_ass(segments, timing_offset=0.0)
    active = re.findall(r"^Dialogue:\s*\d+,([^,]+),([^,]+),Active,", ass, re.M)
    assert active, "expected Active dialogue lines"
    for start, end in active:
        assert _ass_seconds(start) < _ass_seconds(end), f"negative/zero-duration Active line: {start} >= {end}"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_karaoke_subtitle.py::test_no_negative_duration_active_lines_on_overlap -q`
Expected: FAIL (seg2's Active line is emitted with Start > End).

- [ ] **Step 3: Fix the Active-line emission**

In `pikaraoke/lib/karaoke_subtitle.py`, in the second-pass layout loop, change the Active-line block (currently lines ~306-312) so the displayed End preserves the line's fill duration when its row was busy (never landing before `actual_start`), and the row's free-time tracks that displayed end:

```python
        # Active: starts when position is free, ends at singing end
        actual_start = max(start, pos_free_at[my_y])
        # When the row was busy past this line's own end, shift the End by the same
        # delay so it preserves the fill duration instead of producing Start>End (which
        # libass renders for zero frames -> the whole lyric line silently vanishes).
        display_end = max(end, actual_start + (end - start))
        pos_free_at[my_y] = display_end
        lines.append(
            f"Dialogue: 1,{_format_ass_time(actual_start)},{_format_ass_time(display_end)},Active,,0,0,0,,"
            f"{{\\an2\\pos(1920,{my_y})}}{kf_text}"
        )
```

(When the row is free at `start` — the normal case — `actual_start == start`, so `display_end == end` and `pos_free_at[my_y] == end`: identical to the old behavior. Only the delayed case changes.)

- [ ] **Step 4: Run the test, then the full suite**

Run: `uv run --no-sync pytest tests/unit/test_karaoke_subtitle.py -q`
Expected: PASS (the new test + all existing 34 subtitle tests — the normal-case behavior is unchanged).
Run: `uv run --no-sync pytest tests/ -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pikaraoke/lib/karaoke_subtitle.py tests/unit/test_karaoke_subtitle.py
git commit -m "fix: prevent negative-duration ASS lines from silently vanishing in two-line layout"
```

---

### Task 2: Stop deleting repeated chorus / long lines on the aligned-lyrics path

`vocal_separator.py:437` runs the full `_filter_whisper_hallucinations` on the ALIGNED online-lyric segments (human-written text). That filter's repeat-dedup (`>3` occurrences, adjacent-duplicate) and `>20s` rules are meant for raw Whisper hallucinations, but on real lyrics they delete legitimate repeated choruses/hooks and long post-interlude lines → those lines show NO subtitle. Add an `online_aligned` flag that skips those repeat/long-line rules for the aligned path (keeping the keyword/regex credit-line filtering).

**Files:**
- Modify: `pikaraoke/lib/karaoke_subtitle.py` (`_filter_whisper_hallucinations` signature + the repeat/long rules)
- Modify: `pikaraoke/lib/vocal_separator.py:437` (pass `online_aligned=True`)
- Test: `tests/unit/test_karaoke_subtitle.py` (filter behavior) + `tests/unit/test_karaoke_subtitle.py` (call-site content-assert)

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_karaoke_subtitle.py` (it already imports `_filter_whisper_hallucinations`; add `import os` at top if absent):

```python
def _chorus_segs():
    # 5 consecutive identical chorus lines (legitimate in CJK pop)
    return [
        {"text": "啦啦啦", "start": i * 3.0, "end": i * 3.0 + 2.0, "no_speech_prob": 0.0}
        for i in range(5)
    ]


def test_aligned_path_keeps_repeated_chorus_lines():
    kept = _filter_whisper_hallucinations(_chorus_segs(), online_aligned=True)
    assert len(kept) == 5  # all repeated chorus lines preserved on the aligned path


def test_aligned_path_keeps_long_lines():
    long_seg = [{"text": "間奏後的長句", "start": 0.0, "end": 25.0, "no_speech_prob": 0.0}]
    assert len(_filter_whisper_hallucinations(long_seg, online_aligned=True)) == 1


def test_raw_whisper_path_still_dedupes_and_drops_long():
    # default online_aligned=False keeps the existing raw-Whisper behavior
    assert len(_filter_whisper_hallucinations(_chorus_segs())) < 5  # adjacent-dup dedup
    long_seg = [{"text": "x", "start": 0.0, "end": 25.0, "no_speech_prob": 0.0}]
    assert len(_filter_whisper_hallucinations(long_seg)) == 0  # >20s dropped


def test_vocal_separator_uses_online_aligned_filter():
    vs = os.path.join(
        os.path.dirname(__file__), "..", "..", "pikaraoke", "lib", "vocal_separator.py"
    )
    with open(vs, encoding="utf-8") as f:
        src = f.read()
    assert "_filter_whisper_hallucinations(aligned, online_aligned=True)" in src
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --no-sync pytest tests/unit/test_karaoke_subtitle.py -k "aligned_path or online_aligned" -q`
Expected: FAIL (`_filter_whisper_hallucinations` has no `online_aligned` parameter yet → TypeError; and the call-site assert fails).

- [ ] **Step 3: Add the `online_aligned` flag to the filter**

In `pikaraoke/lib/karaoke_subtitle.py`, change the `_filter_whisper_hallucinations` signature and gate the repeat/long-line rules. The function header becomes:

```python
def _filter_whisper_hallucinations(segments, online_aligned=False):
```

Then guard the `>20s` rule (currently ~line 154):

```python
        # Skip suspiciously long segments (normal lyric line is 2-10s). Online lyrics
        # legitimately have long lines after interludes, so only apply to raw Whisper.
        if not online_aligned and duration > 20:
            continue
```

And guard the repeat-dedup block (currently ~lines 171-180) so it only runs for raw Whisper (online lyrics legitimately repeat choruses):

```python
        # Repeat-based dedup catches Whisper hallucinations that loop the same phrase,
        # but online lyrics legitimately repeat choruses/hooks -> skip for aligned text.
        if not online_aligned:
            normalized = re.sub(r"\s+", "", text)
            seen_texts[normalized] = seen_texts.get(normalized, 0) + 1
            if seen_texts[normalized] > 3:
                continue
            # Skip consecutive identical lines (adjacent duplicates)
            if normalized == prev_normalized:
                continue
            prev_normalized = normalized

        filtered.append(seg)
```

(The keyword/regex credit-line filtering, the `no_speech_prob`, `duration < 0.1`, and single-char-noise rules still run in both paths — they are harmless for clean online text and still catch credit lines.)

- [ ] **Step 4: Use the flag at the aligned call-site**

In `pikaraoke/lib/vocal_separator.py`, line 437, change:

```python
            segments = _filter_whisper_hallucinations(aligned, online_aligned=True)
```

(was `_filter_whisper_hallucinations(aligned)`. Leave the two fallback/raw call-sites at lines 440 and 446 as-is — they correctly filter raw Whisper output.)

- [ ] **Step 5: Run the tests, then the full suite**

Run: `uv run --no-sync pytest tests/unit/test_karaoke_subtitle.py -q`
Expected: PASS (new + existing).
Run: `uv run --no-sync pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pikaraoke/lib/karaoke_subtitle.py pikaraoke/lib/vocal_separator.py tests/unit/test_karaoke_subtitle.py
git commit -m "fix: keep repeated chorus and long lines when generating subtitles from aligned online lyrics"
```

---

## Done — Definition
- `uv run --no-sync pytest tests/ -q` green (780 baseline + the new subtitle tests).
- No ASS Dialogue line is emitted with Start >= End (lines no longer silently vanish).
- Repeated chorus/hook lines and long post-interlude lines survive on the aligned-lyrics path; the raw-Whisper path keeps its dedup/long-line filtering.
- No `[ai]` deps required; the fixes are validated purely by unit tests.

## Next (after this)
- Resume desync (frontend splash.js octopus offset) — needs manual verification.
- Root-cause DTW alignment in `lyrics_corrector.py` — needs `[ai]` deps installed to validate; biggest win for the "越唱越歪" drift.
- Color direction — confirm preference with the user before flipping.
