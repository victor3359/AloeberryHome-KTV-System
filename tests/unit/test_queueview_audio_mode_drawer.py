import os

_QV = os.path.join(
    os.path.dirname(__file__), "..", "..", "pikaraoke", "templates", "queueview.html"
)


def _read():
    with open(_QV, encoding="utf-8") as f:
        return f.read()


def test_mini_player_click_excludes_audio_mode_buttons():
    """Clicking the 原唱/伴奏 (audio-mode) buttons must NOT open/toggle the control-panel
    drawer. The .mini-player click-to-open handler only excluded .mini-player__btn, so the
    audio-mode buttons fell through and toggled the drawer on every switch. The fix excludes
    the .mini-player__audio-mode container from the open-drawer condition.
    """
    html = _read()
    assert 'class="mini-player__audio-mode"' in html  # the audio-mode container exists
    assert "closest('.mini-player__btn, .mini-player__audio-mode')" in html
