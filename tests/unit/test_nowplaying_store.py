import os

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_BASE = os.path.join(_PKG, "templates", "base.html")
_STORE = os.path.join(_PKG, "static", "core", "nowPlayingStore.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_store_module_exists_and_exports_api():
    js = _read(_STORE)
    assert "export function subscribe(" in js
    assert "export function refresh(" in js


def test_base_html_bootstraps_store():
    base = _read(_BASE)
    assert 'import * as nowPlayingStore from "core/nowPlayingStore.js";' in base
    assert "window.nowPlayingStore = nowPlayingStore;" in base


def test_store_refetches_on_socket_reconnect():
    """P1-9: the socket auto-reconnects after a phone sleeps/backgrounds. The store must
    re-fetch /now_playing on 'connect' or it keeps showing the pre-sleep song until the next
    state-change broadcast (position updates ride a separate event). splash.js already re-fetches
    on connect; the store, advertised as the single source of truth for phone pages, must too."""
    js = _read(_STORE)
    assert 'socket.on("connect", refresh)' in js
    # idempotent: off before on so re-subscribes don't stack duplicate connect handlers.
    assert 'socket.off("connect", refresh)' in js


_SONGPICKER = os.path.join(_PKG, "templates", "songpicker.html")


def test_songpicker_uses_store_for_now_playing():
    html = _read(_SONGPICKER)
    assert 'window.nowPlayingStore.subscribe("songpicker-mini", updateMiniStrip);' in html
    # songpicker no longer binds its own now_playing socket handler or fetches /now_playing itself
    assert 'sock.on("now_playing"' not in html
    assert "updateMiniStrip(JSON.parse(data))" not in html
