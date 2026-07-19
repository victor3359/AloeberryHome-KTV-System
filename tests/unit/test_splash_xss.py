import os

_SPLASH_JS = os.path.join(
    os.path.dirname(__file__), "..", "..", "pikaraoke", "static", "js", "splash.js"
)


def _read():
    with open(_SPLASH_JS, encoding="utf-8") as f:
        return f.read()


def test_splash_escapes_song_and_singer_names_before_html_injection():
    """P2-3: the now-playing/up-next overlays and the leaderboard build HTML with .html() from
    the song title (a YouTube filename) and the singer name (a free-text phone prompt), both
    untrusted. A name like <img src=x onerror=...> would run on the splash session, and a '<' or
    '&' in a Chinese title would break the overlay. Escape them first."""
    js = _read()
    assert "const escapeHtml" in js or "function escapeHtml" in js
    assert "escapeHtml(np.now_playing)" in js
    assert "escapeHtml(np.now_playing_user)" in js
    assert "escapeHtml(np.up_next)" in js
    assert "escapeHtml(entry.singer)" in js
