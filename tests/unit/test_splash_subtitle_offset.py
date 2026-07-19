"""Guard tests for the splash subtitle re-seek offset wiring (move 移調/切音軌 desync fix)."""

from __future__ import annotations

import os
import re

# The subtitle offset wiring moved into modules/subtitles.js in slice 7.
_SUBTITLES = os.path.join(
    os.path.dirname(__file__), "..", "..", "pikaraoke", "static", "js", "modules", "subtitles.js"
)


def _read() -> str:
    with open(_SUBTITLES, encoding="utf-8") as f:
        return f.read()


def test_octopus_options_set_time_offset_from_subtitle_offset():
    """After a 移調/切音軌 re-seek the media is shifted by ffmpeg -ss but the ASS keeps absolute
    times; the octopus instance must apply now_playing_subtitle_offset as timeOffset or every
    lyric fires start_position seconds too early for the rest of the song."""
    js = _read()
    assert re.search(r"timeOffset\s*:", js), "octopus options must pass a timeOffset"
    assert (
        "now_playing_subtitle_offset" in js
    ), "timeOffset must derive from the server-authoritative now_playing_subtitle_offset"


def test_subtitle_offset_refreshed_on_kept_instance():
    """When the subtitle URL is unchanged the octopus instance is reused; its timeOffset must
    still be refreshed so a seek-base change without a URL change re-aligns (robust against
    future deterministic stream uids)."""
    js = _read()
    assert re.search(r"_octopus\.timeOffset\s*=", js)
