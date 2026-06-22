import os

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_BASE = os.path.join(_PKG, "templates", "base.html")
_SOCKET = os.path.join(_PKG, "static", "core", "socketClient.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_socket_client_module_exists_and_defines_get_socket():
    js = _read(_SOCKET)
    assert "window.getSocket" in js
    assert "function getSocket(" in js


def test_base_html_loads_socket_client_as_classic_script():
    base = _read(_BASE)
    assert "core/socketClient.js" in base
    # Must be a classic script: page scripts call getSocket() at parse time,
    # before deferred ES modules run, so the tag must not be type="module".
    tag = base.split("core/socketClient.js")[1].split(">")[0]
    assert 'type="module"' not in tag


_QUEUEVIEW = os.path.join(_PKG, "templates", "queueview.html")


def test_queueview_uses_socket_singleton():
    html = _read(_QUEUEVIEW)
    assert "window.socket = window.getSocket();" in html
    assert "window.socket = io()" not in html
