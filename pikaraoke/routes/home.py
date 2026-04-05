"""Home page route — redirects to queue view."""

from flask import redirect, url_for
from flask_smorest import Blueprint

home_bp = Blueprint("home", __name__)


@home_bp.route("/")
def home():
    """Redirect home to queue view (merged now-playing + queue)."""
    return redirect(url_for("queue.queue"))
