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


@scores_bp.get("/library/stats")
def library_stats():
    """Get song library statistics."""
    k = get_karaoke_instance()
    return jsonify(k.song_db.get_stats())


@scores_bp.get("/library/songs")
def library_songs():
    """Get all songs with metadata."""
    k = get_karaoke_instance()
    artist = request.args.get("artist")
    language = request.args.get("language")
    q = request.args.get("q")
    if q:
        return jsonify(k.song_db.search(q))
    if artist:
        return jsonify(k.song_db.get_songs_by_artist(artist))
    if language:
        return jsonify(k.song_db.get_songs_by_language(language))
    return jsonify(k.song_db.get_all_songs())


@scores_bp.get("/library/artists")
def library_artists():
    """Get artist list with song counts."""
    k = get_karaoke_instance()
    return jsonify(k.song_db.get_artists())


@scores_bp.get("/library/top")
def library_top():
    """Get most played songs."""
    k = get_karaoke_instance()
    limit = request.args.get("n", 50, type=int)
    return jsonify(k.song_db.get_top_played(limit))


@scores_bp.post("/reprocess")
def reprocess_song():
    """Delete stems and lyrics for a song, then re-run vocal separation + transcription."""
    k = get_karaoke_instance()
    data = request.get_json(silent=True) or request.form
    song_path = (data.get("song") or "").strip()
    if not song_path:
        return jsonify({"ok": False, "error": "Missing song path"}), 400

    import os
    import threading

    base = os.path.splitext(song_path)[0]
    # Delete existing stems and lyrics
    for suffix in ("_vocals.mp3", "_instrumental.mp3", "_karaoke.ass"):
        path = base + suffix
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    # Re-process in background thread
    title = k.song_manager.filename_from_path(song_path, remove_youtube_id=True)

    def _reprocess():
        try:
            k.vocal_separator.process(song_path, title=title)
        except Exception as e:
            import logging

            logging.warning("Reprocess failed for %s: %s", song_path, e)

    threading.Thread(target=_reprocess, daemon=True).start()
    return jsonify({"ok": True, "message": f"Reprocessing: {title}"})


@scores_bp.get("/session_summary")
def get_session_summary():
    """Return the session summary statistics."""
    k = get_karaoke_instance()
    return jsonify(k.get_session_summary())
