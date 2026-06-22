"""File management routes for browsing, editing, and deleting songs."""

from __future__ import annotations

import logging
import os
import re

import flask_babel
from flask import flash, redirect, render_template, request, url_for
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from pikaraoke.lib.current_app import get_karaoke_instance, get_site_name, is_admin

_ = flask_babel.gettext


files_bp = Blueprint("files", __name__)


def _detect_language(filename: str) -> str:
    """Detect language from filename based on Unicode character sets."""
    if re.search(r"[\u3040-\u30ff]", filename):
        return "japanese"
    if re.search(r"[\uac00-\ud7af]", filename):
        return "korean"
    if re.search(r"[\u4e00-\u9fff]", filename):
        return "chinese"
    return "english"


def _extract_artist(filename: str) -> str | None:
    """Extract artist from 'Artist - Title' or 'Artist – Title' naming pattern."""
    m = re.match(r"^(.+?)\s+[-\u2013]\s+.+", filename)
    return m.group(1).strip() if m else None


class SongReferrerQuery(Schema):
    song = fields.String(required=True, metadata={"description": "Path to the song file"})
    referrer = fields.String(metadata={"description": "URL to redirect back to"})


class EditFileForm(Schema):
    new_file_name = fields.String(
        required=True, metadata={"description": "New filename (without extension)"}
    )
    old_file_name = fields.String(
        required=True, metadata={"description": "Current full path of the song file"}
    )
    referrer = fields.String(metadata={"description": "URL to redirect back to after editing"})


@files_bp.route("/browse", methods=["GET"])
def browse():
    """Browse available songs page — redirects to songpicker."""
    from flask import redirect, url_for

    # Preserve query parameters in redirect
    args = request.args.to_dict()
    return redirect(url_for("songpicker.songpicker", **args))


@files_bp.route("/files/delete", methods=["GET"])
@files_bp.arguments(SongReferrerQuery, location="query")
def delete_file(query):
    """Delete a song file."""
    k = get_karaoke_instance()
    song_path = query["song"]
    if k.queue_manager.is_song_in_queue(song_path):
        flash(
            # MSG: Message shown after trying to delete a song that is in the queue.
            _("Error: Can't delete this song because it is in the current queue")
            + ": "
            + song_path,
            "is-danger",
        )
    else:
        display_name = k.song_manager.filename_from_path(song_path)
        k.song_manager.delete(song_path)
        # Clean up play stats and favorites for deleted song
        k.play_stats.remove(display_name)
        flash(_("Song deleted: %s") % display_name, "is-warning")
    referrer = query.get("referrer") or url_for("files.browse")
    return redirect(referrer)


@files_bp.route("/files/edit", methods=["GET"])
@files_bp.arguments(SongReferrerQuery, location="query")
def edit_file(query):
    """Show the song rename page."""
    k = get_karaoke_instance()
    site_name = get_site_name()
    song_path = query["song"]
    referrer = query.get("referrer") or url_for("files.browse")
    if k.queue_manager.is_song_in_queue(song_path):
        # MSG: Message shown after trying to edit a song that is in the queue.
        flash(
            _("Error: Can't edit this song because it is in the current queue: ") + song_path,
            "is-danger",
        )
        return redirect(referrer)
    return render_template(
        "edit.html",
        site_title=site_name,
        title="Song File Edit",
        song=song_path,
        referrer=referrer,
    )


@files_bp.route("/files/edit", methods=["POST"])
@files_bp.arguments(EditFileForm, location="form")
def rename_file(form):
    """Process a song rename."""
    k = get_karaoke_instance()
    referrer = form.get("referrer") or url_for("files.browse")
    new_name = form["new_file_name"]
    old_name = form["old_file_name"]
    if k.queue_manager.is_song_in_queue(old_name):
        # check one more time just in case someone added it during editing
        # MSG: Message shown after trying to edit a song that is in the queue.
        flash(
            _("Error: Can't edit this song because it is in the current queue: ") + old_name,
            "is-danger",
        )
    else:
        file_extension = os.path.splitext(old_name)[1]
        if os.path.isfile(os.path.join(k.song_manager.download_path, new_name + file_extension)):
            flash(
                # MSG: Message shown after trying to rename a file to a name that already exists.
                _("Error renaming file: '%s' to '%s', Filename already exists")
                % (old_name, new_name + file_extension),
                "is-danger",
            )
        else:
            try:
                k.song_manager.rename(old_name, new_name)
            except OSError as e:
                logging.error(f"Error renaming file: {e}")
                flash(
                    _("Error renaming file: '%s' to '%s', %s") % (old_name, new_name, e),
                    "is-danger",
                )
            else:
                flash(
                    # MSG: Message shown after renaming a file.
                    _("Renamed file: %s to %s") % (old_name, new_name),
                    "is-warning",
                )
    return redirect(referrer)
