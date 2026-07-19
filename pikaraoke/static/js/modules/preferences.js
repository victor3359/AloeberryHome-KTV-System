// Live preference application for the splash screen. The effect registry fans out to many
// subsystems (bg-media, session-ui clock, the video, the screensaver timeout, the theme), so its
// callbacks are injected via createPreferences rather than imported — this module stays free of
// splash/bg-media/session-ui coupling and is the "assemble-last" registry of the modularization.

export const parsePreferenceValue = (value) => {
  if (typeof value !== "string") return value;
  if (value === "True") return true;
  if (value === "False") return false;
  const num = Number(value);
  return !isNaN(num) && value.trim() !== "" ? num : value;
};

export function createPreferences(deps) {
  const {
    playBGVideo,
    playBGMusic,
    shouldBackgroundMediaPlay,
    getBackgroundMusicPlayer,
    startClock,
    stopClock,
    getVideoPlayer,
    isMediaPlaying,
    setScreensaverTimeout,
  } = deps;

  const $ = window.jQuery;

  const toggleBGMedia = (configKey, playFn, disabled) => {
    PikaraokeConfig[configKey] = disabled;
    disabled ? playFn(false) : shouldBackgroundMediaPlay() && playFn(true);
  };

  const effects = {
    disable_bg_video: (v) => toggleBGMedia("disableBgVideo", playBGVideo, v),
    disable_bg_music: (v) => toggleBGMedia("disableBgMusic", playBGMusic, v),
    disable_score: (v) => {
      PikaraokeConfig.disableScore = v;
    },
    show_splash_clock: (v) => {
      PikaraokeConfig.showSplashClock = v;
      v ? startClock() : (stopClock(), $("#clock").hide());
    },
    hide_overlay: (v) => {
      PikaraokeConfig.hideOverlay = v;
      $("#bottom-container, #top-container").toggle(!v);
    },
    hide_url: (v) => {
      $("#qr-code, #screensaver-qr").toggle(!v);
    },
    bg_music_volume: (v) => {
      PikaraokeConfig.bgMusicVolume = v;
      const player = getBackgroundMusicPlayer();
      if (isMediaPlaying(player)) $(player).animate({ volume: v }, 1000);
    },
    screensaver_timeout: (v) => {
      setScreensaverTimeout(v);
      PikaraokeConfig.screensaverTimeout = v;
    },
    volume: (v) => {
      const video = getVideoPlayer();
      if (video) video.volume = v;
    },
    hide_notifications: (v) => {
      PikaraokeConfig.hideNotifications = v;
    },
    splash_theme: (v) => {
      document.body.className = document.body.className.replace(/theme-\S+/g, "");
      if (v && v !== "classic") document.body.classList.add("theme-" + v);
    },
  };

  const applyPreferenceUpdate = (data) => {
    const effect = effects[data.key];
    if (effect) effect(parsePreferenceValue(data.value));
  };

  const applyPreferencesReset = (defaults) => {
    Object.entries(defaults).forEach(([key, value]) => applyPreferenceUpdate({ key, value }));
  };

  return { applyPreferenceUpdate, applyPreferencesReset };
}
