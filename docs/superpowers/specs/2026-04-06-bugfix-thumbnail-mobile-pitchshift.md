# Bug Fix: Thumbnail Rename, Mobile Layout, Pitch Shift

Date: 2026-04-06

## Overview

Four user-reported issues affecting core KTV experience:

1. Song thumbnail disappears after renaming
2. Mobile song picker shows truncated song names
3. Pitch shift (key change) also changes playback speed
4. Pitch shift UI resets to 0 when navigating between pages

## Bug 1: Thumbnail Lost on Rename

### Root Cause

`song_manager.rename()` updates the filesystem and in-memory `SongList` but does NOT update `song_database.py`. The database is keyed by `file_path` (UNIQUE constraint), so after rename the new path has no matching record. Template looks up new path, gets None, thumbnail disappears.

### Fix

**song_database.py** — add `rename_song()` method (DB already has `remove_song()`):

```python
def rename_song(self, old_path: str, new_path: str) -> None:
    with self._lock:
        self._conn.execute(
            "UPDATE songs SET file_path = ? WHERE file_path = ?", (new_path, old_path)
        )
        self._conn.commit()
```

**song_manager.py** — accept optional `song_db` in `__init__()`, call it in `rename()` and `delete()`:

`SongManager` doesn't currently hold a reference to `song_db`. Pass it as an optional constructor parameter so ALL rename/delete call sites (routes/files.py, routes/batch_song_renamer.py, download_manager.py) automatically benefit:

```python
def __init__(self, download_path: str, song_db=None) -> None:
    self.download_path = download_path
    self.songs = SongList()
    self.song_db = song_db
```

In `rename()`, after filesystem + SongList update:

```python
if self.song_db:
    self.song_db.rename_song(old_path, new_path)
```

In `delete()`, after filesystem cleanup:

```python
if self.song_db:
    self.song_db.remove_song(file_path)
```

**karaoke.py** — pass `song_db` to `SongManager` (after both are created):

```python
self.song_manager.song_db = self.song_db
```

Note: 4 call sites exist for rename (`files.py`, `batch_song_renamer.py` x2, `download_manager.py`). By fixing `SongManager` internally, all are covered.

### Files Modified

- `pikaraoke/lib/song_database.py` — add `rename_song()` method
- `pikaraoke/lib/song_manager.py` — accept `song_db`, call it in `rename()` and `delete()`
- `pikaraoke/karaoke.py` — wire `song_db` into `song_manager`

## Bug 2: Mobile Song Name Truncated

### Root Cause

Mobile uses 2-column grid. Each card is ~165px wide. After thumbnail (48px), padding (26px), and action button (40px), only ~51px remains for text. Combined with `white-space: nowrap` in `modern-theme.css`, even short song names are truncated.

### Fix

**modern-theme.css** — single column on mobile:

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
}
```

**songpicker.html** — remove inline CSS rules that conflict with `modern-theme.css` for `.sp-song-grid` and `.sp-song-card__title`. Consolidate all layout rules in `modern-theme.css` to avoid specificity conflicts.

Single column gives ~350px card width on mobile, with ~230px for text — sufficient for most Chinese song titles.

### Files Modified

- `pikaraoke/static/modern-theme.css` — add mobile breakpoint, single column + title wrap
- `pikaraoke/templates/songpicker.html` — remove conflicting inline styles

## Bug 3: Pitch Shift Changes Speed

### Root Cause

`pitch-shift-processor.js` claims to be a "Phase Vocoder" but implements simple resampling — reading the input buffer at a different rate. Resampling inherently couples pitch and tempo: pitch up = slow down, pitch down = speed up.

The fallback path is worse: `video.playbackRate` with `preservesPitch = false` explicitly changes both.

### Fix — SoundTouchJS Integration

Replace the broken resampling with SoundTouchJS's TDHS (Time Domain Harmonic Scaling) algorithm.

**Add SoundTouchJS library:**

- Download `soundtouch.js` (~50KB, MIT license) into `pikaraoke/static/js/`
- No npm dependency — direct file include to keep project simple

**Rewrite `pitch-shift-processor.js`:**

- Import SoundTouch core via `importScripts()` in AudioWorklet context
- Use `SoundTouch` class with `pitchSemitones` property
- Feed input buffer to SoundTouch in `process()`, read pitch-shifted output
- TDHS is time-domain, low latency (~100ms), no FFT required

**Update `splash.js` initialization:**

- AudioWorklet `addModule()` loads the rewritten processor
- Fallback changed from `preservesPitch = false` (broken) to showing a "browser not supported" message — no silent degradation to wrong behavior

### Technical Constraints

- AudioWorklet runs in a separate thread; unlike regular Web Workers, `importScripts()` is NOT available in AudioWorkletGlobalScope
- SoundTouch core algorithm must be bundled directly into the processor file (concatenated or inlined), not loaded separately
- Alternative: use a ScriptProcessorNode (deprecated but universally supported) with SoundTouch as a main-thread fallback if AudioWorklet bundling proves problematic

### Files Modified

- `pikaraoke/static/js/soundtouch.js` — new file (SoundTouchJS library)
- `pikaraoke/static/js/pitch-shift-processor.js` — rewrite with SoundTouch TDHS
- `pikaraoke/static/js/splash.js` — update initialization, fix fallback

## Bug 4: Pitch Shift UI Resets to 0

### Root Cause

The real-time pitch shift value (from Socket.IO `pitch_shift` event) is only stored client-side in the splash screen's AudioWorklet. When the user navigates away from the control panel (queueview.html) and returns, the page reinitializes with slider at 0. The server has no record of the current pitch shift value.

This is a display-only bug — the audio remains correctly shifted.

### Fix

**karaoke.py** — add `current_pitch_shift` state:

```python
self.current_pitch_shift = 0
```

Reset in `reset_now_playing()` when song changes.

**socket_events.py** — store value on server when received:

```python
@socketio.on("pitch_shift")
def pitch_shift(semitones):
    k = get_karaoke_instance()
    k.current_pitch_shift = int(semitones)
    socketio.emit("pitch_shift", semitones, namespace="/")
```

**karaoke.py `get_now_playing()`** — include in broadcast data:

```python
"current_pitch_shift": self.current_pitch_shift
```

**queueview.html** — read value on page load from `now_playing` event:

```javascript
socket.on("now_playing", function(data) {
    if (data.current_pitch_shift !== undefined) {
        $("#cp-transpose").val(data.current_pitch_shift);
        // Update display label
    }
});
```

### Behavior

- Adjust during playback → stored server-side → survives page navigation
- Song changes → auto-resets to 0
- Server restart → all lost (acceptable per requirements)

### Files Modified

- `pikaraoke/karaoke.py` — add `current_pitch_shift` field, include in `get_now_playing()`
- `pikaraoke/routes/socket_events.py` — store pitch shift value
- `pikaraoke/templates/queueview.html` — read and display current value on load

## Implementation Order

1. Bug 1 (thumbnail rename) — smallest scope, standalone fix
2. Bug 4 (pitch UI sync) — small scope, standalone fix
3. Bug 2 (mobile layout) — CSS-only, no backend changes
4. Bug 3 (SoundTouchJS) — largest scope, depends on external library integration

## Testing

- Bug 1: Rename a song, verify thumbnail persists. Delete a song, verify DB record removed.
- Bug 2: Open song picker on mobile (or narrow browser), verify single column with full song names.
- Bug 3: Adjust key +-6 semitones, verify pitch changes without speed change.
- Bug 4: Adjust key, navigate to another tab, return — slider shows current value.
