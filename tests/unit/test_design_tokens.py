import os

_CSS = os.path.join(
    os.path.dirname(__file__), "..", "..", "pikaraoke", "static", "modern-theme.css"
)


def _read():
    with open(_CSS, encoding="utf-8") as f:
        return f.read()


def test_neon_night_accent_values_applied():
    css = _read()
    assert "--accent-cyan: #22d3ee;" in css
    assert "--text-primary: #ffffff;" in css
    assert "--color-success: #34d399;" in css


def test_neon_night_new_tokens_added():
    css = _read()
    assert "--accent-2: #e879f9;" in css
    assert "--accent-violet: #a78bfa;" in css
    assert "--panel: rgba(255, 255, 255, 0.06);" in css
