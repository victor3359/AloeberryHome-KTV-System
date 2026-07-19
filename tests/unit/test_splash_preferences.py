import os
import re

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_SPLASH_JS = os.path.join(_PKG, "static", "js", "splash.js")
_PREFS = os.path.join(_PKG, "static", "js", "modules", "preferences.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_preferences_module_exports():
    """Slice 6: the preference registry + value parser live in modules/preferences.js. The registry
    fans out to many subsystems, so it is a createPreferences(deps) factory (injected callbacks),
    the modularization's assemble-last piece."""
    m = _read(_PREFS)
    assert re.search(r"^export const parsePreferenceValue\b", m, re.M)
    assert re.search(r"^export function createPreferences\b", m, re.M)


def test_splash_uses_the_preferences_factory():
    js = _read(_SPLASH_JS)
    assert 'from "/static/js/modules/preferences.js"' in js
    assert "createPreferences({" in js
    # the registry, parser, and toggleBGMedia moved out of splash.
    assert "const PREFERENCE_EFFECTS =" not in js
    assert "const parsePreferenceValue =" not in js
    assert "const toggleBGMedia =" not in js
    # the socket handlers still dispatch through the factory's returned functions.
    assert "applyPreferenceUpdate" in js and "applyPreferencesReset" in js
