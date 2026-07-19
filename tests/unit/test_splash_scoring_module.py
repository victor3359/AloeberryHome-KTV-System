import os
import re

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_SCORE = os.path.join(_PKG, "static", "score.js")
_SPLASH_JS = os.path.join(_PKG, "static", "js", "splash.js")
_SPLASH_HTML = os.path.join(_PKG, "templates", "splash.html")
_PLAYER_CORE = os.path.join(_PKG, "static", "js", "modules", "player-core.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_score_js_exports_entrypoints():
    """Slice 4 Task 2: score.js becomes an ES module exporting startScore + setScoreReviews."""
    score = _read(_SCORE)
    assert re.search(r"^export async function startScore\b", score, re.M)
    assert re.search(r"^export function setScoreReviews\b", score, re.M)


def test_score_js_owns_score_reviews_off_window():
    """scoreReviews is a module-private binding in score.js now (the de-globalization trap: an
    imported binding is read-only for the importer, so ownership moves INTO score.js with a
    setter for the socket writer)."""
    score = _read(_SCORE)
    assert "window.scoreReviews" not in score
    assert re.search(r"^let scoreReviews\b", score, re.M)
    assert "scoreReviews.low" in score and "scoreReviews.high" in score


def test_splash_imports_scoring_and_drops_window_score_reviews():
    # The scoring entrypoints are imported by player-core (slice 9), which wires the socket handler.
    pc = _read(_PLAYER_CORE)
    assert re.search(r'import \{[^}]*\bstartScore\b[^}]*\} from "/static/score\.js"', pc)
    assert "setScoreReviews(phrases)" in pc
    # window.scoreReviews is gone from both splash and player-core.
    assert "window.scoreReviews" not in _read(_SPLASH_JS)
    assert "window.scoreReviews" not in pc


def test_splash_html_no_classic_score_script_tag():
    html = _read(_SPLASH_HTML)
    assert "filename='score.js'" not in html and 'filename="score.js"' not in html
    # fireworks.js stays classic (launchFireworkShow is a kept window global read by score.js).
    assert "fireworks.js" in html
