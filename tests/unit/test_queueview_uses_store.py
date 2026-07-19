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


def test_queueview_store_subscribe_runs_after_dom_ready():
    """P0-2: window.nowPlayingStore is assigned by base.html's deferred <script type="module">,
    which runs AFTER all parse-time classic scripts. If queueview touches nowPlayingStore at the
    top level (as it did), a hard load of /queue — the phone's landing page, since '/' redirects
    to /queue — throws 'nowPlayingStore is undefined' and kills the rest of the inline script (no
    queue list, no mini player, dead buttons). The subscribe must live inside $(function(){}),
    like songpicker, so it runs once the deferred module has assigned the global."""
    html = _read()
    ready_idx = html.index("$(function")
    # The dereference is what throws; a bare comment mentioning the store is harmless.
    assert "nowPlayingStore.subscribe" not in html[:ready_idx], (
        "queueview dereferences nowPlayingStore at parse time (before $(function)) — "
        "a hard load of /queue will crash"
    )
    assert "nowPlayingStore.subscribe" in html[ready_idx:]
