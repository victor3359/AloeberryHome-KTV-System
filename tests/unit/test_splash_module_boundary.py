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
    """After slice 4 the only classic helper still loaded alongside the splash module is
    fireworks.js, which touches no splash-owned global. score.js is now an ES module that owns
    scoreReviews itself, so no classic->module bare-global crossing remains."""
    fireworks = _read(_FIREWORKS)
    assert re.search(r"(?<!window\.)\bscoreReviews\b", fireworks) is None
    score = _read(_SCORE)
    assert "window.scoreReviews" not in score  # owned as a module-private binding now


def test_pitch_helpers_export_their_classes_and_drop_the_window_leak():
    """Slice 4 converted the pitch helpers to ES modules: they now export their class and no
    longer attach it to window; splash imports them. Lock the new direction."""
    pa = _read(_PITCH_ANALYZER)
    pm = _read(_PITCH_METER)
    assert "export class PitchAnalyzer" in pa
    assert "export class PitchMeter" in pm
    assert "window.PitchAnalyzer" not in pa
    assert "window.PitchMeter" not in pm


def test_screensaver_import_specifier_is_the_static_path():
    """The screensaver import uses the absolute static path (Flask serves /static by default;
    there is no custom static_url_path). Pin it so a path/serving change fails loudly here rather
    than at runtime on the TV."""
    js = _read(_SPLASH_JS)
    assert 'from "/static/screensaver.js"' in js
