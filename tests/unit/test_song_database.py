"""Unit tests for SongDatabase."""

from __future__ import annotations

from pikaraoke.lib.song_database import SongDatabase


class TestRenameSong:
    def test_rename_updates_file_path(self, tmp_path):
        db = SongDatabase(str(tmp_path))
        db.upsert_song(
            "/songs/Old---abc.mp4",
            artist="Test",
            thumbnail_url="http://example.com/thumb.jpg",
        )
        db.rename_song("/songs/Old---abc.mp4", "/songs/New---abc.mp4")
        result = db.get_song("/songs/New---abc.mp4")
        assert result is not None
        assert result["thumbnail_url"] == "http://example.com/thumb.jpg"

    def test_rename_old_path_gone(self, tmp_path):
        db = SongDatabase(str(tmp_path))
        db.upsert_song("/songs/Old---abc.mp4", artist="Test")
        db.rename_song("/songs/Old---abc.mp4", "/songs/New---abc.mp4")
        assert db.get_song("/songs/Old---abc.mp4") is None

    def test_rename_nonexistent_no_error(self, tmp_path):
        db = SongDatabase(str(tmp_path))
        db.rename_song("/songs/Ghost.mp4", "/songs/New.mp4")
