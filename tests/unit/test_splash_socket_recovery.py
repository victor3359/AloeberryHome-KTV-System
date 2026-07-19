import os

# setupSocketEvents moved into modules/player-core.js in slice 9.
_PLAYER_CORE = os.path.join(
    os.path.dirname(__file__), "..", "..", "pikaraoke", "static", "js", "modules", "player-core.js"
)


def _read():
    with open(_PLAYER_CORE, encoding="utf-8") as f:
        return f.read()


def test_setup_socket_events_clears_handlers_before_binding():
    """P1-3: handleSocketRecovery re-invokes setupSocketEvents on visibilitychange, and io()
    returns the same multiplexed socket, so without clearing first every handler binds twice.
    Two 'connect' handlers emit register_splash twice from one sid; the server's second reply is
    'slave' (master_splash_id is now that very sid), so the only TV self-demotes and endSong
    stops emitting end_song -> the queue stalls when a song finishes. setupSocketEvents must drop
    existing handlers before (re)binding so it is safe to call again."""
    js = _read()
    setup_idx = js.index("const setupSocketEvents")
    first_on_idx = js.index("socket.on(", setup_idx)
    head = js[setup_idx:first_on_idx]
    assert "socket.off(" in head, "setupSocketEvents must clear handlers before re-binding"
