// HLS.js multi-audio pipeline for the splash player. Owns the Hls instance and the audio-track map
// (original/instrumental) so the player-core and the audio_mode_switch handler share one source.
// Hls is a classic-script global, resolved from module scope.

let _hls = null;
let _audioTrackMap = null;

// Set up HLS playback for an .m3u8 stream. browser = { isChrome, isEdge, isMobileSafari }.
export function setupHls(streamUrl, video, browser) {
  const useNativeHLS =
    video.canPlayType("application/vnd.apple.mpegurl") &&
    !browser.isChrome &&
    !browser.isEdge &&
    !browser.isMobileSafari;
  if (useNativeHLS) {
    video.src = streamUrl;
    return;
  }
  if (_hls) {
    _hls.destroy();
    _hls = null;
  }
  _hls = new Hls({ startPosition: 0 });

  // Detect multi-audio tracks for instant switching. FFmpeg names them audio_1/audio_2/audio_3 but
  // order is deterministic: index 0 = original, 1 = instrumental, 2 = guide.
  _hls.on(Hls.Events.AUDIO_TRACKS_UPDATED, function () {
    _audioTrackMap = null;
    if (_hls.audioTracks && _hls.audioTracks.length > 1) {
      _audioTrackMap = { original: 0, instrumental: 1 };
      console.log("Multi-audio detected: " + _hls.audioTracks.length + " tracks");
      _hls.audioTrack = 1; // default to instrumental (karaoke mode)
    }
  });

  _hls.loadSource(streamUrl);
  _hls.attachMedia(video);
}

export function destroyHls() {
  if (_hls) {
    _hls.destroy();
    _hls = null;
  }
}

// Instant audio-track switch (multi-audio HLS): mode = "original" | "instrumental".
export function switchAudioTrack(mode, video) {
  if (!_hls || !_audioTrackMap) return;
  const trackIndex = _audioTrackMap[mode];
  if (trackIndex !== undefined) {
    _hls.audioTrack = trackIndex;
    // Force a seeked event to re-enable SubtitlesOctopus's timeupdate listener. An HLS audio-track
    // switch triggers seeking but not always seeked, which permanently disables subtitle sync.
    if (video) {
      setTimeout(function () {
        const pos = video.currentTime;
        video.currentTime = pos + 0.001;
        video.currentTime = pos;
      }, 150);
    }
    console.log("Audio track switched to: " + mode + " (index " + trackIndex + ")");
  }
}
