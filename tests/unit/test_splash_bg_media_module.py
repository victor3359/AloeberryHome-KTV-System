import os
import re

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_BGMEDIA = os.path.join(_PKG, "static", "js", "modules", "bg-media.js")
_SPLASH = os.path.join(_PKG, "static", "js", "splash.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_bg_media_module_exists_and_exports_api():
    bg = _read(_BGMEDIA)
    assert "export function initBgMedia(" in bg
    for name in (
        "getBackgroundMusicPlayer",
        "playBGMusic",
        "playBGVideo",
        "shouldBackgroundMediaPlay",
        "updateBackgroundMediaState",
        "setupBackgroundMusicPlayer",
    ):
        assert re.search(rf"export const {name}\b", bg), f"bg-media.js must export {name}"


def test_bg_media_uses_injected_accessors_not_splash_state():
    """bg-media must read splash state only through injected accessors, never as bare globals
    (it is a module that imports nothing from splash)."""
    bg = _read(_BGMEDIA)
    assert "getAutoplayConfirmed()" in bg
    assert "getNowPlaying()" in bg
    # No bare splash-owned identifiers leaked into the module.
    assert re.search(r"(?<!\.)\bautoplayConfirmed\b", bg) is None
    assert re.search(r"(?<![.\w])\bnowPlaying\b", bg) is None
    # bg-media imports nothing back from splash (no circular import).
    assert re.search(r'from\s+["\'][^"\']*splash\.js["\']', bg) is None


def test_splash_imports_bg_media_and_inits_it():
    splash = _read(_SPLASH)
    assert "import {" in splash and 'from "/static/js/modules/bg-media.js";' in splash
    # The injected accessors are wired exactly once.
    assert "initBgMedia({" in splash
    assert "getNowPlaying: () => (player ? player.getNowPlaying()" in splash
    assert "getAutoplayConfirmed: () => autoplayConfirmed" in splash
    assert "isMediaPlaying" in splash  # passed through as the third dep


def test_splash_no_longer_defines_bg_media_functions_or_state():
    """The moved definitions must be gone from splash (else module import collides with a local
    declaration of the same name -> SyntaxError)."""
    splash = _read(_SPLASH)
    for decl in (
        "const playBGMusic =",
        "const playBGVideo =",
        "const shouldBackgroundMediaPlay =",
        "const updateBackgroundMediaState =",
        "const setupBackgroundMusicPlayer =",
        "const getBackgroundMusicPlayer =",
        "const getBackgroundVideoPlayer =",
        "const getNextBgMusicSong =",
        "let bg_playlist =",
        "let bgMediaResumeTimeout =",
        "const bgMediaResumeDelay =",
        "const hasBgVideo =",
    ):
        assert (
            decl not in splash
        ), f"splash.js must no longer define `{decl}` (moved to bg-media.js)"
    # player-core helpers that must STAY in splash:
    assert "const isMediaPlaying =" in splash
    assert "const getVideoPlayer =" in splash
