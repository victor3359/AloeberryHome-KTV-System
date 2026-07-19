def test_get_recommendations_same_language_does_not_crash(tmp_path):
    """P3/latent: the same-language recommendation query had one fewer bind param than
    placeholders — the ``language=?`` was left unbound — raising sqlite3.ProgrammingError for any
    song that has a language, i.e. a 500 on /library/recommend (and a leaked connection). Bind
    current['language']."""
    from pikaraoke.lib.song_database import SongDatabase

    db = SongDatabase(str(tmp_path))
    db.upsert_song("/songs/A---aaaaaaaaaaa.mp4", artist="X", language="zh", play_count=5)
    db.upsert_song("/songs/B---bbbbbbbbbbb.mp4", artist="Y", language="zh", play_count=3)
    db.upsert_song("/songs/C---ccccccccccc.mp4", artist="Z", language="zh", play_count=1)

    recs = db.get_recommendations("/songs/A---aaaaaaaaaaa.mp4", limit=5)
    assert isinstance(recs, list)  # must not raise ProgrammingError
    assert "/songs/A---aaaaaaaaaaa.mp4" not in {r["file_path"] for r in recs}
