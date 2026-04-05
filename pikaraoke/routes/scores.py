"""Routes for recording and retrieving per-session karaoke scores and stats."""

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


@scores_bp.get("/play_stats/top")
def get_top_songs():
    """Return the top most-played songs across all sessions."""
    k = get_karaoke_instance()
    n = request.args.get("n", 50, type=int)
    top = k.play_stats.get_top(n)
    return jsonify([{"title": t, "count": c} for t, c in top])


@scores_bp.post("/favorites/toggle")
def toggle_favorite():
    """Toggle a song as favorite for the current user."""
    k = get_karaoke_instance()
    data = request.get_json(silent=True) or request.form
    user = (data.get("user") or "").strip()
    filename = (data.get("filename") or "").strip()
    if not user or not filename:
        return jsonify({"ok": False, "error": "Missing user or filename"}), 400
    is_fav = k.favorites.toggle(user, filename)
    return jsonify({"ok": True, "is_favorite": is_fav})


@scores_bp.get("/favorites")
def get_favorites():
    """Return the current user's favorite songs."""
    k = get_karaoke_instance()
    user = request.args.get("user", "").strip()
    if not user:
        return jsonify([])
    return jsonify(k.favorites.get_user_favorites(user))


@scores_bp.get("/session_summary")
def get_session_summary():
    """Return the session summary statistics."""
    k = get_karaoke_instance()
    return jsonify(k.get_session_summary())
