import os
import re

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_SPLASH_JS = os.path.join(_PKG, "static", "js", "splash.js")
_SESSION_UI = os.path.join(_PKG, "static", "js", "modules", "session-ui.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_session_ui_module_exports_the_leaf_helpers():
    """Slice 5: the self-contained UI leaves (formatters, toast, clock, session timer) live in
    modules/session-ui.js, each owning its own state."""
    m = _read(_SESSION_UI)
    for name in (
        "formatElapsed",
        "formatTime",
        "escapeHtml",
        "flashNotification",
        "startClock",
        "stopClock",
        "startSessionTimer",
    ):
        assert re.search(rf"^export (const|function) {name}\b", m, re.M), name


def test_splash_imports_session_ui_and_drops_the_definitions():
    js = _read(_SPLASH_JS)
    assert 'from "/static/js/modules/session-ui.js"' in js
    # the definitions moved out of splash (only imported now).
    assert "const flashNotification =" not in js
    assert "const startSessionTimer =" not in js
    assert "const startClock =" not in js
    # the clock/session-timer state moved with them.
    assert "let clockIntervalId" not in js
    assert "let sessionElapsedBase" not in js
