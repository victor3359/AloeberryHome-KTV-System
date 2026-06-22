import os

_TEMPLATE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "pikaraoke", "templates"
)


def test_dead_home_template_removed():
    """home.html is unrendered (the / route redirects to /queue) — must be gone."""
    assert not os.path.exists(os.path.join(_TEMPLATE_DIR, "home.html"))


def test_dead_queue_template_removed():
    """queue.html is unrendered (the live queue page is queueview.html) — must be gone."""
    assert not os.path.exists(os.path.join(_TEMPLATE_DIR, "queue.html"))
