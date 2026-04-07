"""SQLite-based song metadata database.

Stores artist, title, language, play count, stems/lyrics status,
and YouTube metadata for rich search and categorization.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
from typing import Any


class SongDatabase:
    """Manages song metadata in a SQLite database."""

    def __init__(self, data_dir: str) -> None:
        self._db_path = os.path.join(data_dir, "songs.db")
        self._lock = threading.RLock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """CREATE TABLE IF NOT EXISTS songs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT UNIQUE NOT NULL,
                    artist TEXT DEFAULT '',
                    title TEXT DEFAULT '',
                    language TEXT DEFAULT '',
                    duration INTEGER DEFAULT 0,
                    download_date TEXT DEFAULT '',
                    play_count INTEGER DEFAULT 0,
                    has_stems INTEGER DEFAULT 0,
                    has_lyrics INTEGER DEFAULT 0,
                    youtube_id TEXT DEFAULT '',
                    thumbnail_url TEXT DEFAULT ''
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    UNIQUE(user, file_path)
                )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_songs_artist ON songs(artist)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_songs_language ON songs(language)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_songs_play_count ON songs(play_count DESC)"
            )
            conn.commit()
            conn.close()

    def upsert_song(self, file_path: str, **kwargs: Any) -> None:
        """Insert or update a song's metadata."""
        with self._lock:
            conn = self._get_conn()
            # Check if exists
            row = conn.execute("SELECT id FROM songs WHERE file_path=?", (file_path,)).fetchone()
            if row:
                if kwargs:
                    sets = ", ".join(f"{k}=?" for k in kwargs)
                    vals = list(kwargs.values()) + [file_path]
                    conn.execute(f"UPDATE songs SET {sets} WHERE file_path=?", vals)
            else:
                cols = ["file_path"] + list(kwargs.keys())
                placeholders = ", ".join("?" for _ in cols)
                vals = [file_path] + list(kwargs.values())
                conn.execute(f"INSERT INTO songs ({', '.join(cols)}) VALUES ({placeholders})", vals)
            conn.commit()
            conn.close()

    def remove_song(self, file_path: str) -> None:
        """Remove a song and its favorites from the database."""
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM songs WHERE file_path=?", (file_path,))
            conn.execute("DELETE FROM favorites WHERE file_path=?", (file_path,))
            conn.commit()
            conn.close()

    def prune_orphans(self, valid_paths: set[str]) -> int:
        """Delete records whose file_path is not in valid_paths. Returns count removed."""
        removed = 0
        with self._lock:
            conn = self._get_conn()
            db_paths = [r[0] for r in conn.execute("SELECT file_path FROM songs").fetchall()]
            for db_path in db_paths:
                if db_path not in valid_paths:
                    conn.execute("DELETE FROM songs WHERE file_path=?", (db_path,))
                    conn.execute("DELETE FROM favorites WHERE file_path=?", (db_path,))
                    removed += 1
            conn.commit()
            conn.close()
        if removed > 0:
            logging.info("Pruned %d orphan song records from database", removed)
        return removed

    def rename_song(self, old_path: str, new_path: str) -> None:
        """Update a song's file_path in the database after a rename."""
        with self._lock:
            conn = self._get_conn()
            # Remove any stale record at the target path to avoid UNIQUE conflict
            conn.execute("DELETE FROM songs WHERE file_path=?", (new_path,))
            conn.execute(
                "UPDATE songs SET file_path = ? WHERE file_path = ?",
                (new_path, old_path),
            )
            conn.execute(
                "UPDATE favorites SET file_path = ? WHERE file_path = ?",
                (new_path, old_path),
            )
            conn.commit()
            conn.close()

    def get_song(self, file_path: str) -> dict | None:
        """Get a song's metadata."""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute("SELECT * FROM songs WHERE file_path=?", (file_path,)).fetchone()
            conn.close()
            return dict(row) if row else None

    def get_all_songs(self) -> list[dict]:
        """Get all songs ordered by artist then title."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute("SELECT * FROM songs ORDER BY artist, title").fetchall()
            conn.close()
            return [dict(r) for r in rows]

    def get_top_played(self, limit: int = 50) -> list[dict]:
        """Get most played songs."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM songs WHERE play_count > 0 ORDER BY play_count DESC LIMIT ?",
                (limit,),
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]

    def get_artists(self) -> list[dict]:
        """Get artists with song counts, sorted by count descending."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT artist, COUNT(*) as count FROM songs "
                "WHERE artist != '' GROUP BY artist ORDER BY count DESC"
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]

    def get_songs_by_artist(self, artist: str) -> list[dict]:
        """Get all songs by a specific artist."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM songs WHERE artist=? ORDER BY title", (artist,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]

    def get_songs_by_language(self, language: str) -> list[dict]:
        """Get all songs in a specific language."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM songs WHERE language=? ORDER BY artist, title", (language,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]

    def increment_play_count(self, file_path: str) -> None:
        """Increment the play count for a song."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE songs SET play_count = play_count + 1 WHERE file_path=?", (file_path,)
            )
            conn.commit()
            conn.close()

    def search(self, query: str) -> list[dict]:
        """Search songs by artist or title."""
        with self._lock:
            conn = self._get_conn()
            q = f"%{query}%"
            rows = conn.execute(
                "SELECT * FROM songs WHERE artist LIKE ? OR title LIKE ? ORDER BY play_count DESC",
                (q, q),
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]

    def toggle_favorite(self, user: str, file_path: str) -> bool:
        """Toggle favorite. Returns True if now favorited."""
        with self._lock:
            conn = self._get_conn()
            exists = conn.execute(
                "SELECT id FROM favorites WHERE user=? AND file_path=?", (user, file_path)
            ).fetchone()
            if exists:
                conn.execute(
                    "DELETE FROM favorites WHERE user=? AND file_path=?", (user, file_path)
                )
                conn.commit()
                conn.close()
                return False
            conn.execute("INSERT INTO favorites (user, file_path) VALUES (?, ?)", (user, file_path))
            conn.commit()
            conn.close()
            return True

    def get_user_favorites(self, user: str) -> set[str]:
        """Get user's favorite file paths as a set."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute("SELECT file_path FROM favorites WHERE user=?", (user,)).fetchall()
            conn.close()
            return {r["file_path"] for r in rows}

    def get_recommendations(self, file_path: str, limit: int = 10) -> list[dict]:
        """Get song recommendations based on same artist and language."""
        with self._lock:
            conn = self._get_conn()
            current = conn.execute("SELECT * FROM songs WHERE file_path=?", (file_path,)).fetchone()
            if not current:
                # Fallback: return most played songs
                rows = conn.execute(
                    "SELECT * FROM songs WHERE file_path != ? ORDER BY play_count DESC LIMIT ?",
                    (file_path, limit),
                ).fetchall()
                conn.close()
                return [dict(r) for r in rows]

            results = []
            # Same artist, different song
            if current["artist"]:
                rows = conn.execute(
                    "SELECT * FROM songs WHERE artist=? AND file_path!=? ORDER BY play_count DESC LIMIT ?",
                    (current["artist"], file_path, limit // 2),
                ).fetchall()
                results.extend([dict(r) for r in rows])

            # Same language, popular songs
            if current["language"]:
                seen = {file_path} | {r["file_path"] for r in results}
                rows = conn.execute(
                    "SELECT * FROM songs WHERE language=? AND file_path NOT IN ({}) ORDER BY play_count DESC LIMIT ?".format(
                        ",".join("?" for _ in seen)
                    ),
                    (*seen, limit - len(results)),
                ).fetchall()
                results.extend([dict(r) for r in rows])

            conn.close()
            return results[:limit]

    def get_stats(self) -> dict:
        """Get library statistics."""
        with self._lock:
            conn = self._get_conn()
            song_count = conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
            artist_count = conn.execute(
                "SELECT COUNT(DISTINCT artist) FROM songs WHERE artist != ''"
            ).fetchone()[0]
            total_plays = conn.execute("SELECT SUM(play_count) FROM songs").fetchone()[0] or 0
            conn.close()
            return {
                "song_count": song_count,
                "artist_count": artist_count,
                "total_plays": total_plays,
            }

    def sync_from_filesystem(
        self,
        songs: list[str],
        filename_from_path: Any,
        detect_language: Any = None,
    ) -> tuple[int, int]:
        """Sync database with filesystem song list.

        Adds new songs and removes records for songs no longer on disk.
        Returns (added_count, removed_count).
        """
        removed = self.prune_orphans(set(songs))
        added = 0
        for song_path in songs:
            existing = self.get_song(song_path)
            if existing:
                continue

            display_name = filename_from_path(song_path, True)
            # Parse artist - title
            parts = display_name.split(" - ", 1)
            artist = parts[0].strip() if len(parts) > 1 else ""
            title = parts[1].strip() if len(parts) > 1 else display_name

            # Detect language from title
            language = ""
            if detect_language:
                language = detect_language(display_name)

            # Extract YouTube ID
            youtube_id = ""
            base = os.path.splitext(os.path.basename(song_path))[0]
            yt_match = re.search(r"---([A-Za-z0-9_-]{11})$", base)
            if yt_match:
                youtube_id = yt_match.group(1)

            # Check stems/lyrics
            stem_base = os.path.splitext(song_path)[0]
            has_stems = os.path.exists(stem_base + "_instrumental.mp3")
            has_lyrics = os.path.exists(stem_base + "_karaoke.ass")

            thumbnail_url = ""
            if youtube_id:
                thumbnail_url = f"https://img.youtube.com/vi/{youtube_id}/mqdefault.jpg"

            self.upsert_song(
                song_path,
                artist=artist,
                title=title,
                language=language,
                has_stems=int(has_stems),
                has_lyrics=int(has_lyrics),
                youtube_id=youtube_id,
                thumbnail_url=thumbnail_url,
            )
            added += 1

        logging.info(
            "Song database synced: %d added, %d removed (orphaned)", added, removed
        )
        return added, removed
