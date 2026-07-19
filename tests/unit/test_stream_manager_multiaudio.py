def test_stems_usable_for_multi_audio_requires_nonempty(tmp_path):
    """P2-4: a 0-byte stem (crashed Demucs) 'exists' but would feed ffmpeg an empty input,
    failing the whole track with a misleading 'Stream was not playable'. has_stems — which gates
    the phone's audio-mode UI — uses a non-empty check, so the multi-audio playback decision must
    agree, or a song is offered with audio controls hidden yet is permanently unplayable."""
    from pikaraoke.lib.stream_manager import _stems_usable_for_multi_audio

    inst = tmp_path / "i.mp3"
    voc = tmp_path / "v.mp3"
    inst.write_text("x")
    voc.write_text("x")
    assert _stems_usable_for_multi_audio(str(inst), str(voc)) is True

    inst.write_bytes(b"")  # 0-byte instrumental
    assert _stems_usable_for_multi_audio(str(inst), str(voc)) is False
    assert _stems_usable_for_multi_audio(None, str(voc)) is False
    assert _stems_usable_for_multi_audio(str(inst), None) is False
