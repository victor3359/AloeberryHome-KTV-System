import os
import re

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_SPLASH = os.path.join(_PKG, "static", "js", "splash.js")
_SCORE = os.path.join(_PKG, "static", "score.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_score_reviews_owned_by_scoring_module_not_window():
    """After slice 4 score.js owns scoreReviews as a module-private binding (no longer on window);
    splash writes it through setScoreReviews on the socket event, never window.scoreReviews."""
    splash = _read(_SPLASH)
    score = _read(_SCORE)
    assert re.search(r"^let scoreReviews\b", score, re.M)
    assert "window.scoreReviews" not in score
    assert "window.scoreReviews" not in splash
    assert "setScoreReviews(phrases)" in splash
