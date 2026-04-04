"""Per-user song favorites stored in a JSON file.

Each user (identified by cookie name) can bookmark songs for quick access.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path


class Favorites:
    """Manage per-user favorite songs."""

    def __init__(self, data_dir: str) -> None:
        self._path = os.path.join(data_dir, "favorites.json")
        self._data: dict[str, list[str]] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self._path):
            try:
                with open(self._path, encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logging.warning("Could not load favorites: %s", e)
                self._data = {}

    def _save(self) -> None:
        try:
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logging.error("Could not save favorites: %s", e)

    def toggle(self, user: str, filename: str) -> bool:
        """Toggle a song as favorite for a user. Returns True if now favorited."""
        user = user.strip()
        filename = filename.strip()
        if not user or not filename:
            return False

        user_favs = self._data.setdefault(user, [])
        if filename in user_favs:
            user_favs.remove(filename)
            self._save()
            return False

        user_favs.append(filename)
        self._save()
        return True

    def is_favorite(self, user: str, filename: str) -> bool:
        """Check if a song is in user's favorites."""
        return filename.strip() in self._data.get(user.strip(), [])

    def get_user_favorites(self, user: str) -> list[str]:
        """Get all favorites for a user."""
        return list(self._data.get(user.strip(), []))

    def get_favorites_set(self, user: str) -> set[str]:
        """Get favorites as a set for O(1) lookup."""
        return set(self._data.get(user.strip(), []))
