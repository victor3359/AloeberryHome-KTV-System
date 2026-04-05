"""Persistent play count tracking across sessions.

Stores per-song play counts in a JSON file, keyed by cleaned filename.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path


class PlayStats:
    """Track how many times each song has been played across sessions."""

    def __init__(self, data_dir: str) -> None:
        self._lock = threading.RLock()
        self._path = os.path.join(data_dir, "play_stats.json")
        self._counts: dict[str, int] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self._path):
            try:
                with open(self._path, encoding="utf-8") as f:
                    self._counts = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logging.warning("Could not load play stats: %s", e)
                self._counts = {}

    def _save(self) -> None:
        try:
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._counts, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logging.error("Could not save play stats: %s", e)

    def increment(self, filename: str) -> None:
        """Increment the play count for a song (by cleaned display name)."""
        with self._lock:
            key = filename.strip()
            if not key:
                return
            self._counts[key] = self._counts.get(key, 0) + 1
            self._save()

    def get_count(self, filename: str) -> int:
        """Get the play count for a song."""
        return self._counts.get(filename.strip(), 0)

    def get_top(self, n: int = 50) -> list[tuple[str, int]]:
        """Get the top N most-played songs as (filename, count) pairs."""
        with self._lock:
            return sorted(self._counts.items(), key=lambda x: x[1], reverse=True)[:n]

    def get_all_counts(self) -> dict[str, int]:
        """Get all play counts."""
        with self._lock:
            return dict(self._counts)
