import glob
import os

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_SPLASH_JS = os.path.join(_PKG, "static", "js", "splash.js")
_SCREENSAVER = os.path.join(_PKG, "static", "screensaver.js")
_SPLASH_HTML = os.path.join(_PKG, "templates", "splash.html")
_TEMPLATES = os.path.join(_PKG, "templates")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_screensaver_exports_its_functions():
    ss = _read(_SCREENSAVER)
    assert "export function startScreensaver" in ss
    assert "export function stopScreensaver" in ss


def test_splash_js_is_a_module_importing_screensaver():
    splash = _read(_SPLASH_JS)
    assert 'import { startScreensaver, stopScreensaver } from "/static/screensaver.js";' in splash
    # Module top-level bindings are not auto-attached to window; the inline onClick handlers need this.
    assert "window.handleConfirmation = handleConfirmation;" in splash
    # The dead "depends on upstream" comments are gone (dependency is now a real import).
    assert "depends on upstream screensaver.js import" not in splash


def test_splash_html_loads_splash_as_module_and_drops_classic_screensaver():
    html = _read(_SPLASH_HTML)
    assert (
        "<script type=\"module\" src=\"{{ url_for('static', filename='js/splash.js') }}\"></script>"
        in html
    )
    # The classic screensaver.js body tag is removed (it is imported by the module now).
    assert "filename='screensaver.js'" not in html
    # Both inline handlers remain and both resolve to the single window.handleConfirmation.
    assert html.count('onClick="handleConfirmation()"') == 2


def test_no_template_spa_links_to_splash():
    """splash.js is now an ES module; it must stay direct-load-only. An in-app <a href=".../splash">
    would route through spa-navigation.js, which re-injects splash.js as a CLASSIC <script> -> the
    top-level import throws SyntaxError and the TV page renders blank."""
    import re

    for path in glob.glob(os.path.join(_TEMPLATES, "**", "*.html"), recursive=True):
        html = _read(path)
        assert (
            re.search(r'href=["\'][^"\']*/splash\b', html) is None
        ), f"SPA-eligible /splash link in {path}"
