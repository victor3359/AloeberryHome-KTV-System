import os
import re

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_SPLASH = os.path.join(_PKG, "static", "js", "splash.js")
_SCORE = os.path.join(_PKG, "static", "score.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_score_reviews_is_window_scoped():
    """splash.js owns the score-phrases object and score.js reads/writes it. It must live on
    window so it survives splash.js becoming an ES module (module scope would otherwise trap a
    top-level `let` and break score.js's bare reads)."""
    splash = _read(_SPLASH)
    score = _read(_SCORE)
    # splash writes window.scoreReviews at init and on the socket update.
    assert "window.scoreReviews = {" in splash
    assert "window.scoreReviews = phrases" in splash
    # score.js reads/writes window.scoreReviews.
    assert "window.scoreReviews.low" in score
    assert "window.scoreReviews = await r.json()" in score
    # No bare (non-window) scoreReviews reference remains in either file.
    assert re.search(r"(?<!window\.)\bscoreReviews\b", splash) is None
    assert re.search(r"(?<!window\.)\bscoreReviews\b", score) is None
