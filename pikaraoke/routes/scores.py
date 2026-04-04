"""Routes for recording and retrieving per-session karaoke scores."""

from flask import jsonify, request
from flask_smorest import Blueprint

from pikaraoke.lib.current_app import get_karaoke_instance

scores_bp = Blueprint("scores", __name__)


@scores_bp.post("/record_score")
def record_score():
    """Record a score entry for the current singer after a song ends."""
    k = get_karaoke_instance()
    data = request.get_json(silent=True) or request.form
    singer = (data.get("singer") or "").strip()
    song = (data.get("song") or "").strip()
    try:
        score = int(data.get("score", 0))
    except (ValueError, TypeError):
        score = 0
    if singer:
        k.score_history.append({"singer": singer, "score": score, "song": song})
    return jsonify({"ok": True})


@scores_bp.get("/singers")
def get_singers():
    """Return the list of singers who have queued a song this session."""
    k = get_karaoke_instance()
    return jsonify(sorted(k.known_singers))


@scores_bp.get("/history")
def get_history():
    """Return the play history for this session (most recent first)."""
    k = get_karaoke_instance()
    return jsonify(list(reversed(k.play_history)))


@scores_bp.get("/scores")
def get_scores():
    """Return the session leaderboard sorted by average score."""
    k = get_karaoke_instance()
    by_singer: dict[str, list[int]] = {}
    for entry in k.score_history:
        by_singer.setdefault(entry["singer"], []).append(entry["score"])
    leaderboard = sorted(
        [
            {"singer": s, "avg": round(sum(scores) / len(scores)), "count": len(scores)}
            for s, scores in by_singer.items()
        ],
        key=lambda x: x["avg"],
        reverse=True,
    )
    return jsonify(leaderboard)
