import os

_SONGPICKER = os.path.join(
    os.path.dirname(__file__), "..", "..", "pikaraoke", "templates", "songpicker.html"
)


def _read():
    with open(_SONGPICKER, encoding="utf-8") as f:
        return f.read()


def test_browse_card_has_favorite_toggle_markup():
    html = _read()
    assert "sp-fav-toggle" in html
    assert 'data-song="{{ song }}"' in html
    assert "{% if song in user_favorites %}" in html


def test_favorite_toggle_posts_full_song_path_to_route():
    html = _read()
    assert "url_for('scores.toggle_favorite')" in html
    assert "filename: song" in html
    assert "已收藏" in html
    assert "收藏" in html
