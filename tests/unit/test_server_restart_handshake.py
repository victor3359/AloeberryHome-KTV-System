"""Server-restart handshake + subtitle hot-attach wiring.

Real-TV finding (2026-07-20): the living-room splash/remote pages are long-lived — a server
restart (code update) leaves them running STALE JavaScript, so freshly-fixed features (升降Key,
subtitles) look broken on the TV even though the code is correct. The server announces a per-boot
id on every socket connect; pages remember the first id and reload when it changes.
"""

import os

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")


def _read(*parts):
    with open(os.path.join(_PKG, *parts), encoding="utf-8") as f:
        return f.read()


class TestServerHello:
    def test_socket_events_emits_server_hello_on_connect(self):
        py = _read("routes", "socket_events.py")
        assert "SERVER_STARTUP_ID" in py
        assert '"server_hello"' in py or "'server_hello'" in py
        assert '@socketio.on("connect")' in py or "@socketio.on('connect')" in py

    def test_socket_client_reloads_on_new_server_id(self):
        """Phone pages (queue/songpicker) share the socketClient singleton."""
        js = _read("static", "core", "socketClient.js")
        assert "server_hello" in js
        assert "window.location.reload()" in js
        assert "__pikaraokeServerId" in js

    def test_player_core_reloads_on_new_server_id(self):
        """The splash binds its own handler inside setupSocketEvents — its socket.off() rebind
        cycle would drop a listener attached anywhere else."""
        pc = _read("static", "js", "modules", "player-core.js")
        assert 'socket.on("server_hello"' in pc
        assert "window.location.reload()" in pc
        assert "__pikaraokeServerId" in pc


class TestSubtitlesReadyWiring:
    def test_karaoke_subscribes_and_pushes(self):
        """subtitles_ready -> attach to current playback -> push now_playing so the splash's
        updateSubtitles sees the URL flip from null and creates the octopus mid-song."""
        py = _read("karaoke.py")
        assert '"subtitles_ready"' in py
        assert "attach_subtitles" in py
