import os

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_BASE = os.path.join(_PKG, "templates", "base.html")
_UI = os.path.join(_PKG, "static", "core", "ui.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_base_html_declares_import_map():
    base = _read(_BASE)
    assert 'type="importmap"' in base
    assert '"core/": "/static/core/"' in base


def test_base_html_bootstraps_core_ui_module():
    base = _read(_BASE)
    assert 'import { notify } from "core/ui.js";' in base
    assert "window.showNotification = notify;" in base


def test_base_html_inline_shownotification_removed():
    base = _read(_BASE)
    assert "function showNotification(" not in base
    assert "function connectSocket(" not in base


def test_core_ui_module_exists_and_exports_notify():
    ui = _read(_UI)
    assert "export function notify(" in ui
