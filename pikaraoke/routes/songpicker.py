"""Merged search and browse route for the Song Picker page."""

import os
import time
import unicodedata
from collections import Counter
from urllib.parse import unquote

import flask_babel
from flask import render_template, request, url_for
from flask_paginate import Pagination, get_page_parameter
from flask_smorest import Blueprint

from pikaraoke.lib.current_app import get_karaoke_instance, get_site_name, is_admin
from pikaraoke.lib.youtube_dl import get_search_results
from pikaraoke.routes.files import _detect_language, _extract_artist

_ = flask_babel.gettext

songpicker_bp = Blueprint("songpicker", __name__)


@songpicker_bp.route("/songpicker", methods=["GET"])
def songpicker():
    """Song Picker page: merged browse and YouTube search."""
    k = get_karaoke_instance()
    site_name = get_site_name()

    # --- YouTube search handling ---
    # Default: search official MV (no suffix). With karaoke_search: add "karaoke".
    search_string = request.args.get("search_string")
    search_results = None
    karaoke_search = request.args.get("karaoke_search") == "true"

    if search_string:
        query = search_string + " karaoke" if karaoke_search else search_string
        search_results = get_search_results(query)

    # --- Browse filtering ---
    all_songs = k.song_manager.songs
    available_songs = list(all_songs)

    letter = request.args.get("letter")
    if letter:
        result = []
        if letter == "numeric":
            for song in available_songs:
                f = k.song_manager.filename_from_path(song)[0]
                if f.isnumeric():
                    result.append(song)
        else:
            for song in available_songs:
                f = k.song_manager.filename_from_path(song).lower()
                normalized = unicodedata.normalize("NFD", f)
                base_char = normalized[0] if normalized else ""
                if base_char == letter.lower():
                    result.append(song)
        available_songs = result

    lang = request.args.get("lang")
    artist_filter = request.args.get("artist")

    if lang:
        available_songs = [
            s
            for s in available_songs
            if _detect_language(k.song_manager.filename_from_path(s)) == lang
        ]

    if artist_filter:
        available_songs = [
            s
            for s in available_songs
            if _extract_artist(k.song_manager.filename_from_path(s)) == artist_filter
        ]

    # Feature P: Recently added filter (last 7 days)
    filter_mode = request.args.get("filter")
    if filter_mode == "recent":
        cutoff = time.time() - 7 * 86400
        available_songs = [s for s in available_songs if os.path.getmtime(s) > cutoff]
        available_songs.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        sort_order = "Recent"
    elif request.args.get("sort") == "date":
        available_songs = sorted(available_songs, key=lambda x: os.path.getmtime(x), reverse=True)
        sort_order = "Date"
    else:
        sort_order = "Alphabetical"

    # --- Pagination ---
    search_flag = bool(request.args.get("q"))
    page = int(request.args.get("page", 1))
    results_per_page = k.browse_results_per_page

    args_copy = request.args.copy()
    args_copy.pop("_", None)

    page_param = get_page_parameter()
    args_copy[page_param] = "{0}"
    pagination_href = unquote(url_for("songpicker.songpicker", **args_copy.to_dict()))

    pagination = Pagination(
        css_framework="bulma",
        page=page,
        total=len(available_songs),
        search=search_flag,
        record_name="songs",
        per_page=results_per_page,
        display_msg="Showing <b>{start} - {end}</b> of <b>{total}</b> {record_name}",
        href=pagination_href,
    )

    start_index = (page - 1) * results_per_page
    paginated_songs = available_songs[start_index : start_index + results_per_page]

    # --- Queue file set and artists ---
    queue_files = {item["file"] for item in k.queue_manager.queue}
    artist_counts = Counter(
        a for s in all_songs if (a := _extract_artist(k.song_manager.filename_from_path(s)))
    )
    top_artists = [a for a, c in artist_counts.most_common(30) if c >= 2]

    # Feature Q: Full artist directory (all artists with 1+ songs)
    all_artists = sorted(artist_counts.keys())

    # Feature I: Play counts
    play_counts = k.play_stats.get_all_counts()

    # Feature J: Favorites
    from flask import request as req

    current_user = req.cookies.get("user", "")
    user_favorites = k.favorites.get_favorites_set(current_user) if current_user else set()

    return render_template(
        "songpicker.html",
        site_title=site_name,
        title="Song Picker",
        admin=is_admin(),
        songs=all_songs,
        available_songs=paginated_songs,
        queue_files=queue_files,
        fair_queue_enabled=k.enable_fair_queue,
        limit_user_songs_by=k.limit_user_songs_by,
        letter=letter,
        lang=lang,
        artist_filter=artist_filter,
        sort_order=sort_order,
        top_artists=top_artists,
        all_artists=all_artists,
        pagination=pagination,
        search_string=search_string,
        search_results=search_results,
        karaoke_search=karaoke_search,
        play_counts=play_counts,
        user_favorites=user_favorites,
        filter_mode=filter_mode,
    )
