import os

_QV = os.path.join(
    os.path.dirname(__file__), "..", "..", "pikaraoke", "templates", "queueview.html"
)


def _read():
    with open(_QV, encoding="utf-8") as f:
        return f.read()


def test_document_delegated_handlers_are_offed_before_on():
    """SPA re-navigation re-runs this inline script; handlers bound on the persistent
    document stack unless each is removed first. Every $(document)-level click/keydown
    handler must be guarded with a namespaced .off(...) so re-binding is idempotent."""
    html = _read()
    # Namespaced off-guards must exist for each document-delegated handler.
    assert '.off("click.qv", ".queue-song-options-btn")' in html
    assert '.off("click.qv", ".now-playing-options-btn")' in html
    assert '.off("click.qv", ".audio-mode-btn")' in html
    assert '.off("click.qv", ".audio-mode-btn-mini")' in html
    assert '.off("keydown.qv")' in html
    # The old un-guarded delegated forms must be gone.
    assert "$(document).on('click', '.queue-song-options-btn'" not in html
    assert "$(document).on('click', '.now-playing-options-btn'" not in html
    assert '$(document).on("click", ".audio-mode-btn",' not in html
    assert '$(document).on("click", ".audio-mode-btn-mini",' not in html
    assert "$(document).keydown(function" not in html
