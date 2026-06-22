import os

_PKG = os.path.join(os.path.dirname(__file__), "..", "..", "pikaraoke")
_SPLASH = os.path.join(_PKG, "routes", "splash.py")
_RESOLVER = os.path.join(_PKG, "lib", "file_resolver.py")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_splash_passes_url_to_raspi_wifi_text():
    # get_raspi_wifi_text(url: str) requires a url; the caller must pass k.url
    src = _read(_SPLASH)
    assert "get_raspi_wifi_text(k.url)" in src
    assert "get_raspi_wifi_text()" not in src


def test_file_resolver_drops_dead_resolved_file_path_assignment():
    # resolved_file_path was written once and never read; process_file returns None
    src = _read(_RESOLVER)
    assert "self.resolved_file_path" not in src
    assert "self.process_file(file_path)" in src
