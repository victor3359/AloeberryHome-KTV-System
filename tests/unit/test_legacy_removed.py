import os

import pytest
import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from pikaraoke.routes.files import files_bp
from pikaraoke.routes.songpicker import songpicker_bp

_TEMPLATE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "pikaraoke", "templates"
)


@pytest.fixture
def app():
    test_app = Flask(__name__)
    test_app.register_blueprint(files_bp)
    test_app.register_blueprint(songpicker_bp)
    return test_app


@pytest.fixture
def client(app):
    return app.test_client()


def test_files_legacy_template_removed():
    """files.html was the orphaned /browse_legacy page — must be gone."""
    assert not os.path.exists(os.path.join(_TEMPLATE_DIR, "files.html"))


def test_browse_still_redirects_to_songpicker(client):
    """The live /browse entry must still 302-redirect (proves files.py intact)."""
    resp = client.get("/browse")
    assert resp.status_code == 302
    assert "/songpicker" in resp.headers["Location"]


def test_browse_legacy_route_removed(client):
    """/browse_legacy must no longer exist."""
    assert client.get("/browse_legacy").status_code == 404


from pikaraoke.routes.search import search_bp


@pytest.fixture
def search_app():
    test_app = Flask(__name__)
    test_app.register_blueprint(search_bp)
    test_app.register_blueprint(songpicker_bp)
    return test_app


@pytest.fixture
def search_client(search_app):
    return search_app.test_client()


def test_search_legacy_template_removed():
    """search.html was the orphaned /search_legacy page — must be gone."""
    assert not os.path.exists(os.path.join(_TEMPLATE_DIR, "search.html"))


def test_search_still_redirects_to_songpicker(search_client):
    resp = search_client.get("/search")
    assert resp.status_code == 302
    assert "/songpicker" in resp.headers["Location"]


def test_search_legacy_route_removed(search_client):
    assert search_client.get("/search_legacy").status_code == 404
