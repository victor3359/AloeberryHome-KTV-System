import os

_QV = os.path.join(
    os.path.dirname(__file__), "..", "..", "pikaraoke", "templates", "queueview.html"
)


def _read():
    with open(_QV, encoding="utf-8") as f:
        return f.read()


def test_queueview_subscribes_to_store():
    html = _read()
    assert 'window.nowPlayingStore.subscribe("queueview", onNowPlaying);' in html


def test_queueview_no_longer_fetches_or_binds_now_playing_itself():
    html = _read()
    # The store owns the now_playing socket subscription now.
    assert 'window.socket.on("now_playing", window.queuePage_getQueue)' not in html
    # queuePage_getQueue must not fetch /now_playing anymore (queue-only).
    assert "now_playing.now_playing" not in html
    assert "$.when(" not in html


def test_queueview_shares_one_render_function():
    html = _read()
    # Queue-update path and store callback both go through the extracted renderer.
    assert "function rerenderQueueList()" in html
