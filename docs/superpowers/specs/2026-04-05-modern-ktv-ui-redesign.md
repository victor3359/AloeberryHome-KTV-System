# Modern KTV UI/UX Redesign Spec

## Problem

PiKaraoke's current UI uses Bulma's default dark theme with a top navbar and table-based layouts. While functional, it feels like a developer tool rather than a KTV experience. The UI is not touch-optimized: small tap targets, no swipe gestures, hamburger menu on mobile. This redesign modernizes the interface for a home KTV system used primarily on phones and tablets.

## Design Direction

**Style**: Minimal modern (Apple Music aesthetic) with dark neon accent theme.
**Priority**: Mobile-first, touch-friendly. Desktop is secondary but supported.
**Constraint**: No framework change. Keep jQuery + Socket.IO + Bulma (as grid base). CSS-only visual overhaul.

## Color System

| Token | Value | Usage |
|-------|-------|-------|
| `--bg-base` | `#0a0a0f` | Page background |
| `--bg-surface` | `rgba(255,255,255,0.05)` | Card/panel surfaces (with `backdrop-filter: blur(12px)`) |
| `--bg-surface-hover` | `rgba(255,255,255,0.10)` | Hover state on surfaces |
| `--accent-start` | `#7c3aed` | Gradient start (purple) |
| `--accent-end` | `#06b6d4` | Gradient end (cyan) |
| `--accent-gradient` | `linear-gradient(135deg, #7c3aed, #06b6d4)` | Primary accent gradient |
| `--text-primary` | `#f1f5f9` | Primary text |
| `--text-secondary` | `#94a3b8` | Secondary/muted text |
| `--success` | `#10b981` | Queued/success states |
| `--danger` | `#ef4444` | Delete/error states |
| `--warning` | `#f59e0b` | Warnings |

## Navigation: Bottom 3-Tab Bar

### Structure

```
---------------------------------------------
|  [icon]      |  [icon]      |  [icon]     |
|  Dian Ge     |  Pai Dui     |  Geng Duo   |
---------------------------------------------
```

Tabs:
1. **Dian Ge** (Search + Browse merged) -- music note icon
2. **Pai Dui** (Queue + Now Playing merged) -- list icon
3. **Geng Duo** (Info + Rankings + History) -- grid/more icon

### Behavior

- Fixed to viewport bottom, height 60px
- Glassmorphism background (`backdrop-filter: blur(16px)`)
- Active tab: accent gradient underline (3px) + filled icon
- Inactive tab: `--text-secondary` color
- Desktop (>768px): tabs move to top as horizontal navbar, same 3 sections
- Safe area padding for notched phones (`env(safe-area-inset-bottom)`)

## Tab 1: Dian Ge (Song Selection)

Merges current `/search` and `/browse` into a unified song discovery experience.

### Top Search Bar

- Sticky at top, does not scroll away
- Large input: height 48px, border-radius 12px, glassmorphism background
- Placeholder: "Sou Suo Ge Qu Huo Ge Shou..." (search songs or artists)
- Clear button (X) appears when text is entered
- On focus: pill filter bar scrolls up to stay visible below search

### Browse Mode (no search text)

Displayed when the search input is empty.

**Pill Filter Bar** (horizontal scroll):
- Pills: Quan Bu / Zhong Wen / Ri Wen / Han Wen / Ying Wen / Re Men / Zui Ai / Zui Jin
- Active pill: accent gradient background
- Inactive pill: `--bg-surface` background
- Sticky below search bar

**Artist Quick-Access Row** (horizontal scroll):
- Circular avatars (48px) with artist name below
- Generated from `_extract_artist()` data, sorted by song count
- Tap to filter songs by that artist
- Only shown when "Quan Bu" or language filter is active (not on Re Men/Zui Ai/Zui Jin)

**Song Grid** (card layout):
- 2 columns on mobile, 3-4 on desktop
- Each card: glassmorphism surface, border-radius 12px, padding 12px
  - Song title (1 line, ellipsis overflow)
  - Artist name in `--text-secondary` (1 line)
  - Quick "+" button (44x44px touch target) at bottom-right
  - If already queued: "+" replaced with checkmark in `--success` color
  - If favorited: small heart icon at top-right
- Card tap: shows song detail bottom sheet (full title, artist, play count, queue/favorite actions)

**Alphabetical Side Index**:
- Right edge, vertical strip of small dots/letters
- Touch-drag to jump through alphabet
- Only visible in alphabetical sort mode

### Search Mode (has search text)

Displayed when user types in the search input.

**Local Library Results** (top section):
- List layout: each row height 56px minimum
- Left: song title + artist subtitle
- Right: "+" queue button (44x44px)
- Already-queued items show checkmark
- Section header: "Ben Di Ge Ku" with result count

**YouTube Results** (bottom section):
- List layout with thumbnail (60x34px, 16:9 aspect)
- Song title + duration badge + "YouTube" source tag
- Download/queue button
- Preview button (play icon on thumbnail)
- Section header: "YouTube" with "Xu Xia Zai" label

### Swipe Gestures (list items only)

- Swipe left: reveal "Jia Ru Dui Lie" (accent) and "Shou Cang" (pink) action buttons
- Swipe right: quick-add to queue (with haptic feedback if supported)

## Tab 2: Pai Dui (Queue)

Merges current `/` (Home) and `/queue`.

### Mini Player Bar (fixed top of tab)

- Height: 56px, glassmorphism background
- Left side: song title (marquee on overflow) + singer name below
- Progress: thin 2px gradient line below the bar
- Right side: pause/play button (44x44px) + skip button (44x44px)
- Tap on the bar (not buttons): expand to full control panel

### Expanded Control Panel (overlay)

Slides up from mini player bar when tapped. Glassmorphism panel.

- Song title (large) + singer names
- Full progress bar with current time / duration
- Playback controls row: restart / pause-play / skip (large 56px buttons)
- Volume slider with icon
- Key transpose slider (-12 to +12) with current value label
- "Xian Shi Pai Hang Bang" button
- Tap outside or swipe down to collapse back to mini bar

### Queue List

- Drag handle (left edge) for reorder
- Each row: index number + song title + singer name + swipe-left for delete
- Fair queue indicators: colored dot per user
- Empty state: centered illustration + "Qu Dian Ge Ba!" with button to Tab 1
- Bottom: "Sui Ji Jia Ge" button (glassmorphism, accent border)

## Tab 3: Geng Duo (More)

Card-based entry points replacing current `/info` page.

### Layout

Vertical stack of glassmorphism cards:

1. **Pai Hang** (Rankings) card -- tap to expand
   - Re Men Ge Qu (Hot Songs by play count)
   - Ji Fen Bang (Leaderboard)

2. **Li Shi** (History) card -- tap to expand
   - Ben Chang Ji Lu (This session play history)

3. **She Ding** (Settings) card -- tap to expand
   - Volume / BG music volume
   - Display options (clock, overlay, screensaver)
   - Queue options (fair queue, song limit)
   - Score options
   - Language selection

4. **Guan Li** (Admin) card -- only shown for admin users
   - Shua Xin Ge Ku / Geng Xin yt-dlp / Kai Xin Chang (Session Reset)
   - Tui Chu / Guan Ji / Chong Qi
   - Deng Ru / Deng Chu

### Card Interaction

- Tap card header to expand/collapse (accordion style)
- Only one card expanded at a time
- Expanded card shows full content with glassmorphism inner panels

## Touch Optimization Rules

These rules apply globally across all tabs:

| Rule | Value |
|------|-------|
| Minimum tap target | 44 x 44px |
| List row height | >= 56px |
| Button spacing | >= 8px gap |
| Input height | 48px |
| Border radius (cards) | 12px |
| Border radius (pills/buttons) | 8px |
| Border radius (inputs) | 12px |
| Font size (body) | 16px (prevents iOS zoom) |
| Safe area bottom | `env(safe-area-inset-bottom)` |

## Responsive Breakpoints

| Breakpoint | Behavior |
|------------|----------|
| < 768px (mobile) | Bottom tab bar, 2-col grid, full-width search |
| >= 768px (tablet) | Bottom tab bar, 3-col grid |
| >= 1024px (desktop) | Top navbar, 4-col grid, wider layout (max 1100px) |

## Glassmorphism Implementation

```css
.glass {
    background: rgba(255, 255, 255, 0.05);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
}
```

Fallback for browsers without `backdrop-filter`: solid `#1a1a2e` background.

## Files to Modify

### CSS (new/replace)
- **New**: `pikaraoke/static/modern-theme.css` -- complete theme with CSS custom properties, glassmorphism, tab bar, cards, grid, animations
- **Keep**: `pikaraoke/static/bulma.min.css` (grid/responsive utilities only)
- **Remove from imports**: `bulma-dark.css` (replaced by modern-theme.css)
- **Update**: `pikaraoke/static/custom.css` -- remove conflicting styles, keep non-visual utilities

### Templates
- **Modify**: `pikaraoke/templates/base.html` -- bottom tab bar, new CSS imports, restructured layout container
- **Merge into one**: `search.html` + `files.html` content merges into new `pikaraoke/templates/songpicker.html`
- **Merge into one**: `home.html` + `queue.html` content merges into new `pikaraoke/templates/queueview.html`
- **Replace**: `pikaraoke/templates/info.html` -- accordion card layout
- **Keep unchanged**: `splash.html`, `login.html`, `edit.html`, `batch-song-renamer.html`

### Routes
- **New**: `pikaraoke/routes/songpicker.py` -- serves merged search+browse page at `/songpicker`
- **Modify**: `pikaraoke/routes/queue.py` -- serve merged queue+now-playing page
- **Modify**: `pikaraoke/routes/info.py` -- serve restructured more/settings page
- **Modify**: `pikaraoke/routes/home.py` -- redirect `/` to `/queue`

### Backward-Compatible Redirects
Old routes redirect to new locations so bookmarks and external links keep working:
- `/` -> `/queue` (default landing is now the queue/now-playing view)
- `/search` -> `/songpicker`
- `/browse` -> `/songpicker`
- `/queue` stays at `/queue`
- `/info` stays at `/info`

### JavaScript
- **Modify**: `pikaraoke/static/spa-navigation.js` -- update for 3-tab navigation, swipe gestures
- **No changes**: `splash.js`, `score.js`, `screensaver.js`, `fireworks.js` (splash screen is separate)

## What This Spec Does NOT Cover

- Splash/TV screen redesign (separate scope, keep current design)
- New backend features (play counts, favorites, session reset -- those are in the Round 2 feature plan)
- Framework migration (no React/Vue, stay with jQuery)
- Icon font replacement (keep Fontello)

## Verification

1. All 630 existing tests must pass after changes
2. Pre-commit checks must pass
3. Manual verification on:
   - Mobile Chrome (Android) -- touch targets, gestures, tab bar
   - Mobile Safari (iOS) -- safe area, backdrop-filter, gestures
   - Desktop Chrome -- responsive layout switch, keyboard shortcuts still work
   - Tablet -- intermediate layout
4. Lighthouse mobile score should not regress
