import os
import re

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_SPLASH = os.path.join(_PKG, "static", "js", "splash.js")
_SCORE = os.path.join(_PKG, "static", "score.js")
_PLAYER_CORE = os.path.join(_PKG, "static", "js", "modules", "player-core.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_score_reviews_owned_by_scoring_module_not_window():
    """score.js owns scoreReviews as a module-private binding (no longer on window); the socket
    writer (setScoreReviews) lives in player-core since slice 9, never window.scoreReviews."""
    score = _read(_SCORE)
    assert re.search(r"^let scoreReviews\b", score, re.M)
    assert "window.scoreReviews" not in score
    assert "window.scoreReviews" not in _read(_SPLASH)
    pc = _read(_PLAYER_CORE)
    assert "window.scoreReviews" not in pc
    assert "setScoreReviews(phrases)" in pc
