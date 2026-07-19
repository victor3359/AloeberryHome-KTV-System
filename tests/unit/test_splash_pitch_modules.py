import os
import re

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_PA = os.path.join(_PKG, "static", "js", "pitch-analyzer.js")
_PM = os.path.join(_PKG, "static", "js", "pitch-meter.js")
_SPLASH_JS = os.path.join(_PKG, "static", "js", "splash.js")
_SPLASH_HTML = os.path.join(_PKG, "templates", "splash.html")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_pitch_classes_are_exported_not_window_attached():
    """Slice 4 Task 1: pitch-analyzer.js / pitch-meter.js become ES modules that export their
    class instead of leaking it onto window; splash.js imports them."""
    pa, pm = _read(_PA), _read(_PM)
    assert re.search(r"^export class PitchAnalyzer\b", pa, re.M)
    assert re.search(r"^export class PitchMeter\b", pm, re.M)
    assert "window.PitchAnalyzer" not in pa
    assert "window.PitchMeter" not in pm


def test_splash_imports_the_pitch_classes():
    js = _read(_SPLASH_JS)
    assert re.search(
        r'import \{[^}]*\bPitchAnalyzer\b[^}]*\} from "/static/js/pitch-analyzer\.js"', js
    )
    assert re.search(r'import \{[^}]*\bPitchMeter\b[^}]*\} from "/static/js/pitch-meter\.js"', js)


def test_splash_does_not_typeof_guard_an_imported_class():
    # With a static import PitchAnalyzer is always bound; the "is the script loaded" typeof guard
    # is dead and must be removed so it can't mask a missing import.
    js = _read(_SPLASH_JS)
    assert "typeof PitchAnalyzer" not in js


def test_splash_html_no_classic_pitch_script_tags():
    html = _read(_SPLASH_HTML)
    assert "js/pitch-analyzer.js" not in html
    assert "js/pitch-meter.js" not in html
