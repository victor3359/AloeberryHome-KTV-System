// SubtitlesOctopus (libass WASM) lifecycle for the splash player. Owns the octopus instance and
// the last-rendered subtitle URL; updateSubtitles is called on every now_playing update.
// SubtitlesOctopus is a classic-script global, resolved from module scope.

let _octopus = null;
let _currentUrl = null;

export function updateSubtitles(np, video, uiScale) {
  // After a mid-song re-seek (移調/切音軌 -> ffmpeg -ss start_position) the media is re-based so
  // currentTime=0 == start_position into the song, but the ASS keeps absolute song times. Octopus
  // renders at video.currentTime + timeOffset, so timeOffset = the seek base re-aligns subtitles
  // for the rest of the song (0 for fresh plays and the HLS multi-audio instant switch).
  const subtitleOffset = np.now_playing_subtitle_offset || 0;
  const subtitleUrl = np.now_playing_subtitle_url;
  if (subtitleUrl === _currentUrl && _octopus) {
    // Same subtitle file — don't destroy/recreate (prevents stutter on audio switch). Still refresh
    // the offset; SubtitlesOctopus reads .timeOffset live on each internal timeupdate.
    _octopus.timeOffset = subtitleOffset;
  } else {
    if (_octopus) {
      _octopus.dispose();
      _octopus = null;
    }
    _currentUrl = subtitleUrl;
  }
  if (subtitleUrl && video && !_octopus) {
    const options = {
      video: video,
      subUrl: subtitleUrl,
      timeOffset: subtitleOffset,
      fonts: ["/static/fonts/Arial.ttf", "/static/fonts/DroidSansFallback.ttf"],
      renderMode: "wasm-blend",
      targetFps: 60,
      prescaleFactor: 1.5,
      prescaleHeightLimit: 2160,
      debug: false,
      workerUrl: "/static/js/subtitles-octopus-worker.js",
    };
    try {
      _octopus = new SubtitlesOctopus(options);
      if (uiScale) {
        // The canvas SubtitlesOctopus creates is a sibling of the video.
        const canvas = video.parentNode.querySelector("canvas");
        if (canvas) {
          canvas.style.transform = `scale(${uiScale})`;
          canvas.style.transformOrigin = "bottom center";
        }
      }
    } catch (e) {
      console.error(e);
    }
  }
}
