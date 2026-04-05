"""Playback control routes for skip, pause, volume, and transpose."""

import flask_babel
from flask import redirect, request, url_for
from flask_smorest import Blueprint

from pikaraoke.lib.current_app import broadcast_event, get_karaoke_instance

_ = flask_babel.gettext


controller_bp = Blueprint("controller", __name__)


@controller_bp.route("/skip")
def skip():
    """Skip the currently playing song."""
    k = get_karaoke_instance()
    broadcast_event("skip", "user command")
    k.playback_controller.skip()
    return redirect(url_for("home.home"))


@controller_bp.route("/pause")
def pause():
    """Toggle pause/resume playback."""
    k = get_karaoke_instance()
    if k.playback_controller.is_paused:
        broadcast_event("play")
    else:
        broadcast_event("pause")
    k.playback_controller.pause()
    return redirect(url_for("home.home"))


@controller_bp.route("/transpose/<semitones>", methods=["GET"])
def transpose(semitones):
    """Transpose (pitch shift) the current song."""
    k = get_karaoke_instance()
    broadcast_event("skip", "transpose current")
    k.transpose_current(int(semitones))
    return redirect(url_for("home.home"))


@controller_bp.route("/audio_mode/<mode>", methods=["GET"])
def audio_mode(mode):
    """Switch audio mode — instant if multi-audio HLS, or re-queue if single."""
    if mode not in ("original", "instrumental", "guide"):
        return "Invalid audio mode", 400
    k = get_karaoke_instance()
    if k.playback_controller.supports_multi_audio:
        # Instant switch via HLS.js audio track — no re-transcoding
        k.playback_controller.now_playing_audio_mode = mode
        broadcast_event("audio_mode_switch", mode)
    else:
        # Fallback: re-queue with seek position
        broadcast_event("skip", "audio mode change")
        k.change_audio_mode(mode)
    return redirect(url_for("queue.queue"))


@controller_bp.route("/restart")
def restart():
    """Restart the current song from the beginning."""
    k = get_karaoke_instance()
    broadcast_event("restart")
    k.restart()
    return redirect(url_for("home.home"))


@controller_bp.route("/volume/<volume>")
def volume(volume):
    """Set the playback volume."""
    k = get_karaoke_instance()
    broadcast_event("volume", volume)
    k.volume_change(float(volume))
    return redirect(url_for("home.home"))


@controller_bp.route("/vol_up")
def vol_up():
    """Increase volume by 10%."""
    k = get_karaoke_instance()
    broadcast_event("volume", "up")
    k.vol_up()
    return redirect(url_for("home.home"))


@controller_bp.route("/vol_down")
def vol_down():
    """Decrease volume by 10%."""
    k = get_karaoke_instance()
    broadcast_event("volume", "down")
    k.vol_down()
    return redirect(url_for("home.home"))
