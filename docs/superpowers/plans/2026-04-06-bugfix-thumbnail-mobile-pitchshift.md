# Bug Fix: Thumbnail Rename, Mobile Layout, Pitch Shift — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four user-reported bugs: thumbnail lost on rename, mobile song names truncated, pitch shift changes speed, pitch shift UI resets on navigation.

**Architecture:** Four independent fixes. Bug 1 adds DB sync to song rename/delete. Bug 2 switches mobile to single-column grid. Bug 3 replaces broken resampling with `@soundtouchjs/audio-worklet`. Bug 4 stores client-side pitch shift value server-side for UI sync.

**Tech Stack:** Python/Flask, SQLite, CSS Grid, SoundTouchJS AudioWorklet, Socket.IO

______________________________________________________________________

### Task 1: Fix thumbnail lost on song rename

**Files:**

- Modify: `pikaraoke/lib/song_database.py:80-87`

- Modify: `pikaraoke/lib/song_manager.py:31-33,66-75,77-104`

- Modify: `pikaraoke/karaoke.py:220-221`

- Test: `tests/unit/test_song_database.py` (new)

- Test: `tests/unit/test_song_manager.py:75-141`

- \[ \] **Step 1: Write failing test for `SongDatabase.rename_song()`**

Create `tests/unit/test_song_database.py`:

```python
"""Unit tests for SongDatabase."""

from __future__ import annotations

from pikaraoke.lib.song_database import SongDatabase


class TestRenameSong:
    def test_rename_updates_file_path(self, tmp_path):
        db = SongDatabase(str(tmp_path))
        db.upsert_song(
            "/songs/Old---abc.mp4",
            artist="Test",
            thumbnail_url="http://example.com/thumb.jpg",
        )
        db.rename_song("/songs/Old---abc.mp4", "/songs/New---abc.mp4")
        result = db.get_song("/songs/New---abc.mp4")
        assert result is not None
        assert result["thumbnail_url"] == "http://example.com/thumb.jpg"

    def test_rename_old_path_gone(self, tmp_path):
        db = SongDatabase(str(tmp_path))
        db.upsert_song("/songs/Old---abc.mp4", artist="Test")
        db.rename_song("/songs/Old---abc.mp4", "/songs/New---abc.mp4")
        assert db.get_song("/songs/Old---abc.mp4") is None

    def test_rename_nonexistent_no_error(self, tmp_path):
        db = SongDatabase(str(tmp_path))
        db.rename_song("/songs/Ghost.mp4", "/songs/New.mp4")
```

- \[ \] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_song_database.py -v`
Expected: FAIL with `AttributeError: 'SongDatabase' object has no attribute 'rename_song'`

- \[ \] **Step 3: Implement `rename_song()` in `song_database.py`**

Add after the existing `remove_song()` method (after line 87):

```python
def rename_song(self, old_path: str, new_path: str) -> None:
    """Update a song's file_path in the database after a rename."""
    with self._lock:
        conn = self._get_conn()
        conn.execute(
            "UPDATE songs SET file_path = ? WHERE file_path = ?",
            (new_path, old_path),
        )
        conn.commit()
        conn.close()
```

- \[ \] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_song_database.py -v`
Expected: 3 passed

- \[ \] **Step 5: Write failing test for SongManager rename with DB sync**

Add to `tests/unit/test_song_manager.py` in `TestRename` class:

```python
def test_rename_updates_song_db(self, tmp_path):
    from unittest.mock import MagicMock

    song = tmp_path / "Old---abc.mp4"
    song.write_text("fake")
    sm = SongManager(str(tmp_path))
    sm.song_db = MagicMock()
    sm.refresh_songs()
    old_path = _native(song)
    sm.rename(old_path, "New---abc")
    new_path = _native(tmp_path / "New---abc.mp4")
    sm.song_db.rename_song.assert_called_once_with(old_path, new_path)
```

- \[ \] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_song_manager.py::TestRename::test_rename_updates_song_db -v`
Expected: FAIL with `AttributeError: 'SongManager' object has no attribute 'song_db'`

- \[ \] **Step 7: Add `song_db` to SongManager and call it in `rename()`**

In `pikaraoke/lib/song_manager.py`, modify `__init__()` (line 31-33):

```python
def __init__(self, download_path: str, song_db=None) -> None:
    self.download_path = download_path
    self.songs = SongList()
    self.song_db = song_db
```

At the end of `rename()` method, after `self.songs.rename(song_path, new_path)` (after line 104), add:

```python
if self.song_db:
    self.song_db.rename_song(song_path, new_path)
```

- \[ \] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_song_manager.py::TestRename -v`
Expected: All 4 rename tests pass

- \[ \] **Step 9: Write failing test for SongManager delete with DB sync**

Add to `tests/unit/test_song_manager.py` in `TestDelete` class:

```python
def test_delete_removes_from_song_db(self, tmp_path):
    from unittest.mock import MagicMock

    song = tmp_path / "Test---abc.mp4"
    song.write_text("fake")
    sm = SongManager(str(tmp_path))
    sm.song_db = MagicMock()
    sm.refresh_songs()
    sm.delete(_native(song))
    sm.song_db.remove_song.assert_called_once_with(_native(song))
```

- \[ \] **Step 10: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_song_manager.py::TestDelete::test_delete_removes_from_song_db -v`
Expected: FAIL — `remove_song` not called

- \[ \] **Step 11: Add DB cleanup to `delete()`**

In `pikaraoke/lib/song_manager.py`, at the end of `delete()`, after `self.songs.remove(song_path)` (after line 75), add:

```python
if self.song_db:
    self.song_db.remove_song(song_path)
```

- \[ \] **Step 12: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_song_manager.py::TestDelete -v`
Expected: All 5 delete tests pass

- \[ \] **Step 13: Wire `song_db` into `SongManager` in karaoke.py**

In `pikaraoke/karaoke.py`, after `self.song_db = SongDatabase(data_dir)` (line 263), add:

```python
self.song_manager.song_db = self.song_db
```

- \[ \] **Step 14: Run full test suite**

Run: `uv run pytest tests/unit/ -q`
Expected: All tests pass

- \[ \] **Step 15: Commit**

```bash
git add pikaraoke/lib/song_database.py pikaraoke/lib/song_manager.py pikaraoke/karaoke.py tests/unit/test_song_database.py tests/unit/test_song_manager.py
git commit -m "fix: preserve thumbnail and DB record on song rename/delete"
```

______________________________________________________________________

### Task 2: Fix pitch shift UI resets to 0 on navigation

**Files:**

- Modify: `pikaraoke/karaoke.py:562-594`

- Modify: `pikaraoke/routes/socket_events.py:45-48`

- Modify: `pikaraoke/templates/queueview.html:70-72`

- \[ \] **Step 1: Add `current_pitch_shift` state to `karaoke.py`**

In `pikaraoke/karaoke.py`, find the `__init__()` method. After `self.volume = self.preferences.get_or_default("volume")` (wherever volume is initialized), add:

```python
self.current_pitch_shift = 0
```

In `reset_now_playing()` (line 562-566), add reset before the socket update:

```python
def reset_now_playing(self) -> None:
    """Reset all now playing state to defaults."""
    self.playback_controller.reset_now_playing()
    self.current_pitch_shift = 0
    self.volume = self.preferences.get_or_default("volume")
    self.update_now_playing_socket()
```

In `get_now_playing()` (line 568-594), add to the return dict:

```python
return {
    **playback_state,
    "up_next": next_song["title"] if next_song else None,
    "next_user": next_song["user"] if next_song else None,
    "next_user2": next_song.get("user2") if next_song else None,
    "volume": self.volume,
    "session_elapsed": int(time.time() - self.session_start),
    "has_stems": has_stems,
    "current_pitch_shift": self.current_pitch_shift,
}
```

- \[ \] **Step 2: Store pitch shift value in `socket_events.py`**

In `pikaraoke/routes/socket_events.py`, modify the `pitch_shift` handler (lines 45-48):

```python
@socketio.on("pitch_shift")
def pitch_shift(semitones) -> None:
    """Broadcast pitch shift to all splash screens (client-side processing)."""
    k = get_karaoke_instance()
    k.current_pitch_shift = int(semitones)
    socketio.emit("pitch_shift", semitones, namespace="/")
```

This requires importing `get_karaoke_instance`. Check the file's existing imports — it likely already has it or uses a similar pattern.

- \[ \] **Step 3: Update `queueview.html` to read `current_pitch_shift`**

In `pikaraoke/templates/queueview.html`, find the existing transpose sync (lines 70-72):

```javascript
        if (np.now_playing_transpose !== undefined) {
          $("#cp-transpose").val(np.now_playing_transpose);
          $("#cp-transpose-label").text(getSemitonesLabel(np.now_playing_transpose));
        }
```

Replace with logic that prefers `current_pitch_shift` (the client-side value) over `now_playing_transpose` (the server-side FFmpeg value):

```javascript
        var pitchVal = np.current_pitch_shift || np.now_playing_transpose || 0;
        $("#cp-transpose").val(pitchVal);
        $("#cp-transpose-label").text(getSemitonesLabel(pitchVal));
```

- \[ \] **Step 4: Verify import exists**

`pikaraoke/routes/socket_events.py` line 8 already imports `get_karaoke_instance`:

```python
from pikaraoke.lib.current_app import get_karaoke_instance
```

No import changes needed.

- \[ \] **Step 5: Run full test suite**

Run: `uv run pytest tests/unit/ -q`
Expected: All tests pass (no backend test changes needed — this is socket/UI wiring)

- \[ \] **Step 6: Commit**

```bash
git add pikaraoke/karaoke.py pikaraoke/routes/socket_events.py pikaraoke/templates/queueview.html
git commit -m "fix: persist pitch shift UI state across page navigation"
```

______________________________________________________________________

### Task 3: Fix mobile song picker layout — single column

**Files:**

- Modify: `pikaraoke/static/modern-theme.css:2896-2940`

- Modify: `pikaraoke/templates/songpicker.html:5-45`

- \[ \] **Step 1: Add mobile single-column breakpoint to `modern-theme.css`**

In `pikaraoke/static/modern-theme.css`, find the `.sp-song-grid` section (around line 2896). After the existing media queries, add a mobile-specific rule:

```css
@media (max-width: 767px) {
    .sp-song-grid { grid-template-columns: 1fr; }
    .sp-song-card__title {
        white-space: normal;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    .sp-song-card__artist {
        white-space: normal;
    }
}
```

Place this AFTER the existing `@media (min-width: 768px)` and `@media (min-width: 1024px)` rules so it doesn't interfere with larger screens.

- \[ \] **Step 2: Remove conflicting inline CSS from `songpicker.html`**

In `pikaraoke/templates/songpicker.html`, the inline `<style>` block (lines 5-45) redefines `.sp-song-grid` and `.sp-song-card` with `!important` rules that override the theme CSS. Remove these specific rules from the inline block:

Remove this line (around line 18):

```css
  .sp-song-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
  @media (min-width: 768px) { .sp-song-grid { grid-template-columns: repeat(3, 1fr); } }
```

These are already defined in `modern-theme.css`. Keeping them inline with different specificity prevents the mobile breakpoint from working.

Also check if `.sp-song-card` inline definition has any conflicting rules. The inline `.sp-song-card` (line ~14) has `!important` on background/border — those are fine to keep (they're cosmetic overrides). Only remove grid/layout rules that conflict.

- \[ \] **Step 3: Test manually**

Open browser, resize to mobile width (\< 375px), navigate to song picker page. Verify:

- Songs display in single column

- Song titles show up to 2 lines

- Artist names are fully visible

- On desktop (> 768px), grid remains 3 columns

- On large desktop (> 1024px), grid remains 4 columns

- \[ \] **Step 4: Commit**

```bash
git add pikaraoke/static/modern-theme.css pikaraoke/templates/songpicker.html
git commit -m "fix: mobile song picker uses single column for full song names"
```

______________________________________________________________________

### Task 4: Replace pitch shift with SoundTouchJS AudioWorklet

**Files:**

- Create: `pikaraoke/static/js/soundtouch-worklet.js` (download from npm)

- Modify: `pikaraoke/static/js/splash.js:862-894`

- Delete: `pikaraoke/static/js/pitch-shift-processor.js` (replaced)

- \[ \] **Step 1: Download the `@soundtouchjs/audio-worklet` bundle**

```bash
curl -o pikaraoke/static/js/soundtouch-worklet.js "https://cdn.jsdelivr.net/npm/@soundtouchjs/audio-worklet/dist/soundtouch-worklet.js"
```

Verify the file was downloaded and is non-empty:

```bash
wc -c pikaraoke/static/js/soundtouch-worklet.js
```

Expected: ~50-80KB file size.

- \[ \] **Step 2: Rewrite the pitch shift handler in `splash.js`**

In `pikaraoke/static/js/splash.js`, replace the entire `socket.on("pitch_shift", ...)` handler (lines 862-894) with:

```javascript
// Client-side pitch shift via SoundTouchJS AudioWorklet (no tempo change)
socket.on("pitch_shift", async (semitones) => {
  const video = getVideoPlayer();
  if (!video) return;

  // Initialize audio context and SoundTouch worklet on first use
  if (!window._pitchShiftCtx) {
    try {
      window._pitchShiftCtx = new (window.AudioContext || window.webkitAudioContext)();
      await window._pitchShiftCtx.audioWorklet.addModule("/static/js/soundtouch-worklet.js");
      const source = window._pitchShiftCtx.createMediaElementSource(video);
      window._pitchShiftNode = new AudioWorkletNode(window._pitchShiftCtx, "soundtouch-processor");
      source.connect(window._pitchShiftNode);
      window._pitchShiftNode.connect(window._pitchShiftCtx.destination);
      console.log("SoundTouch AudioWorklet initialized");
    } catch (e) {
      console.warn("SoundTouch AudioWorklet failed:", e);
      return;
    }
  }

  // Resume context if suspended (requires user interaction)
  if (window._pitchShiftCtx.state === "suspended") {
    await window._pitchShiftCtx.resume();
  }

  // Set pitch shift via AudioParam (no tempo change)
  window._pitchShiftNode.parameters.get("pitchSemitones").value = semitones;
  console.log("Pitch shift: " + semitones + " semitones (SoundTouch, no tempo change)");
});
```

Key changes from old code:

- `addModule` loads `soundtouch-worklet.js` instead of `pitch-shift-processor.js`

- Node name is `"soundtouch-processor"` (registered by the SoundTouch worklet)

- Uses `parameters.get("pitchSemitones").value` (AudioParam API) instead of `port.postMessage`

- Fallback removed entirely — no silent degradation to broken playbackRate

- \[ \] **Step 3: Delete the old processor file**

```bash
rm pikaraoke/static/js/pitch-shift-processor.js
```

The `soundtouch.min.js` (main-thread library) can stay — it may be used elsewhere or needed later.

- \[ \] **Step 4: Verify no other references to the old processor**

Search for `pitch-shift-processor` in the codebase. The only reference should be gone now (was in `splash.js`).

```bash
grep -r "pitch-shift-processor" pikaraoke/
```

Expected: no matches.

- \[ \] **Step 5: Test manually**

1. Open the KTV system, play a song
2. On the control panel, adjust the key slider to +3
3. Verify: pitch goes UP but playback speed stays the same
4. Adjust to -5
5. Verify: pitch goes DOWN but playback speed stays the same
6. Reset to 0
7. Verify: audio returns to normal

- \[ \] **Step 6: Run full test suite**

Run: `uv run pytest tests/unit/ -q`
Expected: All tests pass (frontend JS changes don't affect Python tests)

- \[ \] **Step 7: Commit**

```bash
git add pikaraoke/static/js/soundtouch-worklet.js pikaraoke/static/js/splash.js
git rm pikaraoke/static/js/pitch-shift-processor.js
git commit -m "fix: replace broken pitch resampling with SoundTouchJS (no tempo change)"
```

______________________________________________________________________

### Task 5: Final integration test and code quality

**Files:**

- All modified files from Tasks 1-4

- \[ \] **Step 1: Run full test suite**

```bash
uv run pytest tests/unit/ -q
```

Expected: All 630+ tests pass.

- \[ \] **Step 2: Run code quality checks**

```bash
uv run pre-commit run --config code_quality/.pre-commit-config.yaml --all-files
```

Fix any linting issues that arise from the modified Python files.

- \[ \] **Step 3: Push to remote**

```bash
git push origin feature/round3-t1t2-evolution
```
