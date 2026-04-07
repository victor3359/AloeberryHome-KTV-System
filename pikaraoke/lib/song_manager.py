"""Song library management: scan, delete, rename, and display name operations."""

from __future__ import annotations

import contextlib
import logging
import os
import re

from pikaraoke.lib.get_platform import is_windows
from pikaraoke.lib.song_list import SongList

# Characters illegal in Windows filenames
_WINDOWS_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*]')


def sanitize_filename(name: str) -> str:
    """Remove characters that are illegal in filenames on the current platform."""
    if is_windows():
        name = _WINDOWS_ILLEGAL_CHARS.sub("-", name)
    return name.strip()


class SongManager:
    """Manages the song library and file operations.

    Owns the SongList instance and provides all song discovery,
    delete, rename, and display name operations.
    """

    def __init__(self, download_path: str, song_db=None) -> None:
        self.download_path = download_path
        self.songs = SongList()
        self.song_db = song_db

    def refresh_songs(self) -> None:
        """Scan the download directory and update the song list.

        Also prunes orphaned database records (songs deleted from disk).
        """
        self.songs.scan_directory(self.download_path)
        if self.song_db:
            songs_set = set(self.songs)
            self.song_db.prune_orphans(songs_set)

    @staticmethod
    def filename_from_path(file_path: str, remove_youtube_id: bool = True) -> str:
        """Extract a clean display name from a file path.

        Args:
            file_path: Full path to the file.
            remove_youtube_id: Strip YouTube ID suffix if present.

        Returns:
            Clean filename without extension or YouTube ID.
        """
        name = os.path.splitext(os.path.basename(file_path))[0]
        if remove_youtube_id:
            name = name.split("---")[0]
            name = re.sub(r"\s*\[[A-Za-z0-9_-]{11}\]$", "", name)
        return name

    def _get_companion_files(self, song_path: str) -> list[str]:
        """Return paths to companion files that exist alongside a song."""
        base = os.path.splitext(song_path)[0]
        companions = []
        for suffix in (".cdg", ".ass", "_karaoke.ass", "_vocals.mp3", "_instrumental.mp3", "_pitch.json"):
            path = base + suffix
            if os.path.exists(path):
                companions.append(path)
        return companions

    def delete(self, song_path: str) -> None:
        """Delete a song file and its associated companion files if present."""
        logging.info(f"Deleting song: {song_path}")
        companions = self._get_companion_files(song_path)
        with contextlib.suppress(FileNotFoundError):
            os.remove(song_path)
        for companion in companions:
            with contextlib.suppress(FileNotFoundError):
                os.remove(companion)
        self.songs.remove(song_path)
        if self.song_db:
            self.song_db.remove_song(song_path)

    def rename(self, song_path: str, new_name: str) -> None:
        """Rename a song file and its associated companion files if present.

        Args:
            song_path: Full path to the current song file.
            new_name: New filename (without extension).
        """
        new_name = sanitize_filename(new_name)
        logging.info(f"Renaming song: '{song_path}' to: {new_name}")
        companions = self._get_companion_files(song_path)
        _, ext = os.path.splitext(song_path)
        new_path = os.path.join(self.download_path, new_name + ext)
        if os.path.exists(new_path) and new_path != song_path:
            os.remove(new_path)
        os.rename(song_path, new_path)
        old_base = os.path.splitext(os.path.basename(song_path))[0]
        for companion in companions:
            comp_basename = os.path.basename(companion)
            # Preserve the suffix after the old base name (e.g., _vocals.mp3, _karaoke.ass)
            if comp_basename.startswith(old_base):
                suffix = comp_basename[len(old_base) :]
            else:
                suffix = os.path.splitext(comp_basename)[1]
            new_comp_path = os.path.join(self.download_path, new_name + suffix)
            if os.path.exists(new_comp_path):
                os.remove(new_comp_path)
            os.rename(companion, new_comp_path)
        self.songs.rename(song_path, new_path)
        if self.song_db:
            self.song_db.rename_song(song_path, new_path)
