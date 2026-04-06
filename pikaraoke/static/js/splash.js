let socket = io();
let mouseTimer = null;
let cursorVisible = false;
let nowPlaying = {};
let octopusInstance = null;
let showMenu = false;
let menuButtonVisible = false;
let autoplayConfirmed = false;
let volume = 0.85;
const playbackStartTimeout = 10000;
const bgMediaResumeDelay = 2000;
let isScoreShown = false;
const hasBgVideo = PikaraokeConfig.hasBgVideo;
let currentVideoUrl = null;
let hlsInstance = null;
let _pitchShiftInitializing = false;
let idleTime = 0;
let screensaverTimeoutSeconds = PikaraokeConfig.screensaverTimeout;
let bg_playlist = [];
let bgMediaResumeTimeout = null;
let scoreReviews = {
  low: ["Better luck next time!"],
  mid: ["Not bad!"],
  high: ["Great job!"],
};
let isMaster = false;
let uiScale = null;
let clockIntervalId = null;
let sessionElapsedBase = 0;
let sessionElapsedTimerId = null;

// Browser detection
const isSafari = /^((?!chrome|android).)*safari/i.test(navigator.userAgent);
const isMobileSafari = isSafari && (/iPhone|iPad|iPod/i.test(navigator.userAgent) || navigator.maxTouchPoints > 1);
const isChrome = /chrome/i.test(navigator.userAgent) && !/edg/i.test(navigator.userAgent);
const isFirefox = /firefox/i.test(navigator.userAgent);
const isEdge = /edg/i.test(navigator.userAgent);
const isSupportedBrowser = isSafari || isChrome || isFirefox || isEdge;

const isMediaPlaying = (media) =>
  !!(
    media.currentTime > 0 &&
    !media.paused &&
    !media.ended &&
    media.readyState > 2
  );

const formatElapsed = (s) => {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  return `${m}:${String(sec).padStart(2, "0")}`;
};

const startSessionTimer = (base) => {
  sessionElapsedBase = base;
  if (sessionElapsedTimerId) clearInterval(sessionElapsedTimerId);
  const el = document.getElementById("session-elapsed-display");
  if (el) el.textContent = formatElapsed(sessionElapsedBase);
  document.getElementById("session-timer").style.display = "";
  sessionElapsedTimerId = setInterval(() => {
    sessionElapsedBase++;
    if (el) el.textContent = formatElapsed(sessionElapsedBase);
  }, 1000);
};

const formatTime = (seconds) => {
  if (isNaN(seconds)) {
    return "00:00";
  }
  const totalSeconds = Math.floor(seconds);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const secs = totalSeconds % 60;
  const formattedMinutes = String(minutes).padStart(2, "0");
  const formattedSeconds = String(secs).padStart(2, "0");
  return `${formattedMinutes}:${formattedSeconds}`;
}

const testAutoplayCapability = async () => {
  // Test if autoplay with audio is allowed using a real video file
  try {
    const testVideo = document.createElement('video');
    testVideo.playsInline = true;
    testVideo.muted = true;  // Start muted (always allowed)
    testVideo.src = "/static/video/test_autoplay.mp4";

    // Wait for video to be ready
    await new Promise((resolve, reject) => {
      testVideo.onloadeddata = resolve;
      testVideo.onerror = reject;
    });

    await testVideo.play();
    // Now try to unmute - this is the real test
    testVideo.muted = false;
    testVideo.volume = 0.01;

    // Brief delay to let browser enforce policy
    await new Promise(resolve => setTimeout(resolve, 500));

    // Check if browser paused or muted the video
    if (testVideo.muted || testVideo.paused) {
      testVideo.pause();
      $('#permissions-modal').addClass('is-active');
    } else {
      testVideo.pause();
      handleConfirmation();
    }
  } catch (e) {
    // Autoplay blocked
    console.log("Autoplay error thrown", e);
    $('#permissions-modal').addClass('is-active');
  }
};

const handleConfirmation = () => {
  $('#permissions-modal').removeClass('is-active');
  autoplayConfirmed = true;
  updateBackgroundMediaState(true);
  loadNowPlaying();
};

const hideVideo = () => {
  $("#video-container").hide();
}

const endSong = async (reason = null, showScore = false) => {
  // Stop mic scoring
  if (window._pitchAnalyzer) {
    window._pitchAnalyzer.stop();
    window._pitchAnalyzer = null;
  }
  if (window._pitchMeter) {
    window._pitchMeter.hide();
  }

  // Stop pitch shift AudioContext
  if (window._pitchShiftNode) {
    window._pitchShiftNode.disconnect();
    window._pitchShiftNode = null;
  }
  if (window._pitchShiftCtx) {
    window._pitchShiftCtx.close().catch(() => {});
    window._pitchShiftCtx = null;
  }

  if (showScore && !PikaraokeConfig.disableScore) {
    const singer = nowPlaying.now_playing_user;
    const song = nowPlaying.now_playing;
    isScoreShown = true;

    // Use mic-based score if available, otherwise random
    let scoreValue;
    if (window._pitchMeter && window._pitchMeter.totalFrames > 10) {
      scoreValue = window._pitchMeter.getScore();
      window._pitchMeter.reset();
    }
    if (scoreValue === undefined) {
      scoreValue = await startScore("/static/");
    } else {
      // Show the calculated score with the existing score animation
      await startScore("/static/", scoreValue);
    }
    isScoreShown = false;
    if (singer && scoreValue !== undefined) {
      $.post("/record_score", { singer, score: scoreValue, song });
    }
  }
  currentVideoUrl = null;
  $("#progress-bar-container").hide();
  $("#progress-bar-fill").css("width", "0%");
  if (nowPlaying.up_next) {
    $("#transition-singer-name").text(nowPlaying.next_user || "");
    $("#transition-song-name").text(nowPlaying.up_next);
    var ts = document.getElementById("transition-screen");
    ts.style.display = "flex";
    ts.classList.remove("transition-enter-active");
    void ts.offsetWidth;
    ts.classList.add("transition-enter-active");
    // Countdown timer
    var delay = PikaraokeConfig.splashDelay || 2;
    var remaining = delay;
    $("#transition-countdown").text("Starting in " + remaining + "s...");
    if (window._transCountdown) clearInterval(window._transCountdown);
    window._transCountdown = setInterval(function() {
      remaining--;
      if (remaining > 0) {
        $("#transition-countdown").text("Starting in " + remaining + "s...");
      } else {
        $("#transition-countdown").text("Preparing...");
        clearInterval(window._transCountdown);
      }
    }, 1000);
  }
  if (hlsInstance) {
    hlsInstance.destroy();
    hlsInstance = null;
  }
  const video = getVideoPlayer();
  video.pause();
  $("#video-source").attr("src", "");
  video.load();
  hideVideo();
  if (isMaster) {
    socket.emit("end_song", reason);
  } else {
    console.log("Slave active (read-only): skipping end_song emission");
  }
}

const getBackgroundMusicPlayer = () => document.getElementById('background-music');
const getBackgroundVideoPlayer = () => document.getElementById('bg-video');
const getVideoPlayer = () => $("#video")[0]

const getNextBgMusicSong = () => {
  let currentSong = getBackgroundMusicPlayer().getAttribute('src');
  let nextSong = bg_playlist[0];
  if (currentSong) {
    let currentIndex = bg_playlist.indexOf(currentSong);
    if (currentIndex >= 0 && currentIndex < bg_playlist.length - 1) {
      nextSong = bg_playlist[currentIndex + 1];
    }
  }
  return nextSong;
}

const playBGMusic = async (play) => {
  const audio = getBackgroundMusicPlayer();
  if (play) {
    if (PikaraokeConfig.disableBgMusic) return;
    if (!autoplayConfirmed) return;
    if (bg_playlist.length === 0) return;

    if (!audio.getAttribute('src')) audio.setAttribute('src', getNextBgMusicSong());

    if (isMediaPlaying(audio)) return;
    audio.volume = 0;
    if (audio.readyState <= 2) await audio.load();
    await audio.play().catch(e => console.log("Autoplay blocked (music)"));
    $(audio).animate({ volume: PikaraokeConfig.bgMusicVolume }, 2000);
  } else {
    if (audio) {
      $(audio).animate({ volume: 0 }, 2000, () => audio.pause());
    }
  }
}

const playBGVideo = async (play) => {
  const bgVideo = getBackgroundVideoPlayer();
  const bgVideoContainer = $('#bg-video-container');

  if (play) {
    if (PikaraokeConfig.disableBgVideo) return;
    if (!autoplayConfirmed) return;

    if (isMediaPlaying(bgVideo)) return;
    $("#bg-video").attr("src", "/stream/bg_video");
    if (bgVideo.readyState <= 2) await bgVideo.load();
    bgVideo.play().catch(() => console.log("Autoplay blocked (video)"));
    bgVideoContainer.fadeIn(2000);
  } else {
    if (bgVideo && isMediaPlaying(bgVideo)) {
      bgVideo.pause();
      bgVideoContainer.fadeOut(2000);
    }
  }
}

const shouldBackgroundMediaPlay = () => {
  return autoplayConfirmed &&
    !nowPlaying.now_playing &&
    !nowPlaying.up_next;
};

const updateBackgroundMediaState = (immediate = false) => {
  // Clear any pending resume
  if (bgMediaResumeTimeout) {
    clearTimeout(bgMediaResumeTimeout);
    bgMediaResumeTimeout = null;
  }

  if (shouldBackgroundMediaPlay()) {
    if (immediate) {
      playBGMusic(true);
      if (hasBgVideo) playBGVideo(true);
    } else {
      bgMediaResumeTimeout = setTimeout(() => {
        bgMediaResumeTimeout = null;
        if (shouldBackgroundMediaPlay()) {
          playBGMusic(true);
          if (hasBgVideo) playBGVideo(true);
        }
      }, bgMediaResumeDelay);
    }
  } else {
    playBGMusic(false);
    playBGVideo(false);
  }
};

const flashNotification = (message, categoryClass) => {
  const sn = $("#splash-notification");
  if (sn.html()) return;
  sn.html(message);
  sn.addClass(categoryClass);
  sn.fadeIn();
  setTimeout(() => {
    sn.fadeOut();
    setTimeout(() => {
      sn.html("");
      sn.removeClass(categoryClass);
    }, 450);
  }, 3000);
}

const setupScreensaver = () => {
  if (screensaverTimeoutSeconds > 0) {
    setInterval(() => {
      let screensaver = document.getElementById('screensaver');
      let video = getVideoPlayer();
      if (isMediaPlaying(video) || cursorVisible) {
        idleTime = 0;
      }
      if (idleTime >= screensaverTimeoutSeconds) {
        if (screensaver.style.visibility === 'hidden') {
          screensaver.style.visibility = 'visible';
          playBGVideo(false);
          startScreensaver(); // depends on upstream screensaver.js import
        }
        if (idleTime > screensaverTimeoutSeconds + 36000) idleTime = screensaverTimeoutSeconds;
      } else {
        if (screensaver.style.visibility === 'visible') {
          screensaver.style.visibility = 'hidden';
          stopScreensaver(); // depends on upstream screensaver.js import
          updateBackgroundMediaState(true);
        }
      }
      idleTime++;
    }, 1000)
  }
}

const handleNowPlayingUpdate = (np) => {
  nowPlaying = np;
  if (np.now_playing) {

    // Handle updating now playing HTML
    let nowPlayingHtml = `<span>${np.now_playing}</span> `;
    if (np.now_playing_transpose !== 0) {
      nowPlayingHtml += `<span class='is-size-6 has-text-success'><b>Key</b>: ${getSemitonesLabel(np.now_playing_transpose)} </span>`;
    }
    $("#now-playing-song").html(nowPlayingHtml);
    const singerLabel = np.now_playing_user2
      ? `${np.now_playing_user} &amp; ${np.now_playing_user2}`
      : np.now_playing_user;
    $("#now-playing-singer").html(singerLabel);
    $("#now-playing").fadeIn();
  } else {
    $("#now-playing").fadeOut();
  }
  if (np.up_next) {
    $("#up-next-song").html(np.up_next);
    const nextSingerLabel = np.next_user2
      ? `${np.next_user} &amp; ${np.next_user2}`
      : np.next_user;
    $("#up-next-singer").html(nextSingerLabel);
    $("#up-next").fadeIn();
  } else {
    $("#up-next").fadeOut();
  }

  // Update session elapsed timer
  if (np.session_elapsed !== undefined) {
    startSessionTimer(np.session_elapsed);
  }

  // Update bg music and video state
  if (np.now_playing || np.up_next) {
    idleTime = 0;
  }
  updateBackgroundMediaState();

  const video = getVideoPlayer();

  // Setup ASS subtitle file if found (skip recreation if URL unchanged)
  const subtitleUrl = np.now_playing_subtitle_url;
  if (subtitleUrl === window._currentSubtitleUrl && octopusInstance) {
    // Same subtitle file — don't destroy/recreate (prevents stutter on audio switch)
  } else {
    if (octopusInstance) {
      octopusInstance.dispose();
      octopusInstance = null;
    }
    window._currentSubtitleUrl = subtitleUrl;
  }
  if (subtitleUrl && video && !octopusInstance) {
    const options = {
      video: video,
      subUrl: subtitleUrl,
      fonts: ["/static/fonts/Arial.ttf", "/static/fonts/DroidSansFallback.ttf"],
      renderMode: "wasm-blend",
      targetFps: 60,
      prescaleFactor: 1.5,
      prescaleHeightLimit: 2160,
      debug: false,
      workerUrl: "/static/js/subtitles-octopus-worker.js"
    };
    try {
      octopusInstance = new SubtitlesOctopus(options);
      if (uiScale) {
        // Find the canvas created by SubtitlesOctopus (sibling of the video)
        const canvas = video.parentNode.querySelector('canvas');
        if (canvas) {
          canvas.style.transform = `scale(${uiScale})`;
          canvas.style.transformOrigin = 'bottom center';
        }
      }
    } catch (e) { console.error(e); }
  }

  if (!np.now_playing_url) {
    $("#progress-bar-container").hide();
    $("#progress-bar-fill").css("width", "0%");
    if (!np.up_next) {
      $("#transition-screen").fadeOut(400, function() { this.classList.remove("transition-enter-active"); });
    }
  }

  if (np.now_playing_url && np.now_playing_url !== currentVideoUrl) {
    // Cleanup old AudioContext before changing song to prevent memory leaks
    if (window._pitchShiftNode) {
      window._pitchShiftNode.disconnect();
      window._pitchShiftNode = null;
    }
    if (window._pitchShiftCtx) {
      window._pitchShiftCtx.close().catch(() => {});
      window._pitchShiftCtx = null;
    }

    $("#transition-screen").fadeOut(400, function() { this.classList.remove("transition-enter-active"); });
    $("#progress-bar-fill").css({"width": "0%", "transition": "none"});
    $("#progress-bar-container").show();
    // Re-enable smooth transition after initial buffering settles
    setTimeout(function() { $("#progress-bar-fill").css("transition", "width 0.8s linear"); }, 3000);
    currentVideoUrl = np.now_playing_url;
    const streamUrl = np.now_playing_url;
    $("#video-source").attr("src", "");
    video.load();
    $("#video-source").attr("src", streamUrl);

    if (streamUrl.endsWith('.m3u8')) {
      const useNativeHLS = video.canPlayType('application/vnd.apple.mpegurl') && !isChrome && !isEdge && !isMobileSafari;
      if (useNativeHLS) {
        video.src = streamUrl;
      } else {
        if (hlsInstance) { hlsInstance.destroy(); hlsInstance = null; }
        hlsInstance = new Hls({ startPosition: 0 });

        // Detect multi-audio tracks for instant switching
        // FFmpeg names them audio_1/audio_2/audio_3 but order is deterministic:
        // index 0 = original, 1 = instrumental, 2 = guide
        hlsInstance.on(Hls.Events.AUDIO_TRACKS_UPDATED, function() {
          window.audioTrackMap = null;
          if (hlsInstance.audioTracks && hlsInstance.audioTracks.length > 1) {
            window.audioTrackMap = { "original": 0, "instrumental": 1 };
            console.log("Multi-audio detected: " + hlsInstance.audioTracks.length + " tracks");
            // Default to instrumental (karaoke mode)
            hlsInstance.audioTrack = 1;
          }
        });

        hlsInstance.loadSource(streamUrl);
        hlsInstance.attachMedia(video);
      }
    }

    video.load();
    if (volume !== np.volume) {
      volume = np.volume;
      video.volume = volume;
    }

    const duration = $("#duration");
    if (np.now_playing_duration) {
      duration.text(`/${formatTime(np.now_playing_duration)}`);
      duration.show();
    } else {
      duration.hide();
    }

    $("#video-container").show();

    video.play().then(() => {
      // Pre-initialize SoundTouch AudioWorklet to avoid first-use latency
      if (!window._pitchShiftCtx && !_pitchShiftInitializing) {
        _pitchShiftInitializing = true;
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        ctx.audioWorklet.addModule("/static/js/soundtouch-worklet.js").then(() => {
          const source = ctx.createMediaElementSource(video);
          const node = new AudioWorkletNode(ctx, "soundtouch-processor");
          source.connect(node);
          node.connect(ctx.destination);
          window._pitchShiftCtx = ctx;
          window._pitchShiftNode = node;
          _pitchShiftInitializing = false;
          console.log("SoundTouch AudioWorklet pre-initialized");
        }).catch(e => {
          console.warn("SoundTouch pre-init failed:", e);
          ctx.close().catch(() => {});
          _pitchShiftInitializing = false;
        });
      }
    }).catch(err => {
      console.error('Play failed:', err);
      setTimeout(() => video.play(), 1000);
    });

    // Initialize mic-based pitch scoring (if not disabled)
    if (!PikaraokeConfig.disableScore && typeof PitchAnalyzer !== "undefined") {
      _initMicScoring(np.now_playing_filename || "");
    }

    if (np.now_playing_position && isMediaPlaying(video)) {
      if (Math.abs(video.currentTime - np.now_playing_position) > 2) {
        console.log("Syncing to server position:", np.now_playing_position);
        video.currentTime = np.now_playing_position;
      }
    }

    setTimeout(() => {
      if (!isMediaPlaying(video) && !video.paused) {
        endSong("failed to start");
      }
    }, playbackStartTimeout);
  }
}

async function loadNowPlaying() {
  const data = await $.get("/now_playing");
  handleNowPlayingUpdate(JSON.parse(data));
}

const setupOverlayMenus = () => {
  if (PikaraokeConfig.hideOverlay) {
    $('#bottom-container').hide();
    $('#top-container').hide();
  }
  $("#menu a").fadeOut(); // start hidden
  const triggerInactivity = () => {
    mouseTimer = null;
    document.body.style.cursor = 'none';
    cursorVisible = false;
    $("#menu a").fadeOut();
    if (PikaraokeConfig.showSplashClock) {
      setTimeout(() => {
        if (!cursorVisible) $("#clock").fadeIn();
      }, 1000);
    }
    menuButtonVisible = false;
  };

  document.onmousemove = function () {
    if (mouseTimer) window.clearTimeout(mouseTimer);
    if (!cursorVisible) {
      document.body.style.cursor = 'default';
      cursorVisible = true;
    }
    if (!menuButtonVisible) {
      $("#menu a").fadeIn();
      $("#clock").hide();
      menuButtonVisible = true;
    }
    mouseTimer = window.setTimeout(triggerInactivity, 5000);
  };

  // Set initial state to hidden
  triggerInactivity();
  $('#menu a').click(function () {
    if (showMenu) {
      $('#menu-container').hide();
      $('#menu-container iframe').attr('src', '');
      showMenu = false;
    } else {
      setUserCookie();
      $("#menu-container").show();
      $("#menu-container iframe").attr("src", "/");
      showMenu = true;
    }
  });
  $('#menu-background').click(function () {
    if (showMenu) {
      $(".navbar-burger").click();
    }
  });
}

const setupVideoPlayer = () => {
  $('#video-container').hide();
  const video = getVideoPlayer();
  video.addEventListener("play", () => {
    $("#video-container").show();
    if (isMaster) {
      setTimeout(() => { socket.emit("start_song") }, 1200);
    }
  });

  // Master reports playback position to server
  setInterval(() => {
    if (isMaster && isMediaPlaying(video)) {
      socket.emit("playback_position", video.currentTime);
    }
  }, 1000);

  video.addEventListener("ended", () => { endSong("complete", true); });
  video.addEventListener("timeupdate", (e) => {
    $("#current").text(formatTime(video.currentTime));
    const duration = video.duration || nowPlaying.now_playing_duration;
    if (duration > 0 && video.currentTime > 2) {
      $("#progress-bar-fill").css("width", (video.currentTime / duration * 100) + "%");
    }
  });
  $("#video source")[0].addEventListener("error", (e) => {
    if (isMediaPlaying(video)) {
      endSong("error while playing");
    }
  });
  window.addEventListener(
    'beforeunload',
    function (event) {
      if (isMediaPlaying(video)) {
        endSong("splash screen closed");
      }
    },
    true
  );
}

const setupBackgroundMusicPlayer = () => {
  $.get("/bg_playlist", function (data) {
    if (data) bg_playlist = data;
  });
  const bgMusic = getBackgroundMusicPlayer();
  bgMusic.addEventListener("ended", async () => {
    bgMusic.setAttribute('src', getNextBgMusicSong());
    await bgMusic.load();
    await bgMusic.play();
  });
}

const handleUnsupportedBrowser = () => {
  if (!isSupportedBrowser) {
    let modalContents = document.getElementById("permissions-modal-content");
    let warningMessage = document.createElement("p");
    warningMessage.classList.add("notification", "is-warning");
    warningMessage.innerHTML =
      PikaraokeConfig.translations.unsupportedBrowser;
    modalContents.prepend(warningMessage);
  }
}

const startClock = () => {
  if (clockIntervalId) return;
  const update = () => {
    const el = document.getElementById('clock');
    if (el) el.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: true });
  };
  update();
  clockIntervalId = setInterval(update, 1000);
}

const stopClock = () => {
  if (!clockIntervalId) return;
  clearInterval(clockIntervalId);
  clockIntervalId = null;
}

const toggleBGMedia = (configKey, playFn, disabled) => {
  PikaraokeConfig[configKey] = disabled;
  disabled ? playFn(false) : shouldBackgroundMediaPlay() && playFn(true);
};

const PREFERENCE_EFFECTS = {
  disable_bg_video:    (v) => toggleBGMedia("disableBgVideo", playBGVideo, v),
  disable_bg_music:    (v) => toggleBGMedia("disableBgMusic", playBGMusic, v),
  disable_score:       (v) => { PikaraokeConfig.disableScore = v; },
  show_splash_clock:   (v) => {
    PikaraokeConfig.showSplashClock = v;
    v ? startClock() : (stopClock(), $("#clock").hide());
  },
  hide_overlay:        (v) => {
    PikaraokeConfig.hideOverlay = v;
    $("#bottom-container, #top-container").toggle(!v);
  },
  hide_url:            (v) => { $("#qr-code, #screensaver-qr").toggle(!v); },
  bg_music_volume:     (v) => {
    PikaraokeConfig.bgMusicVolume = v;
    const player = getBackgroundMusicPlayer();
    if (isMediaPlaying(player)) $(player).animate({ volume: v }, 1000);
  },
  screensaver_timeout: (v) => {
    screensaverTimeoutSeconds = v;
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

const parsePreferenceValue = (value) => {
  if (typeof value !== "string") return value;
  if (value === "True") return true;
  if (value === "False") return false;
  const num = Number(value);
  return !isNaN(num) && value.trim() !== "" ? num : value;
};

const applyPreferenceUpdate = (data) => {
  const effect = PREFERENCE_EFFECTS[data.key];
  if (effect) effect(parsePreferenceValue(data.value));
};

const applyPreferencesReset = (defaults) => {
  Object.entries(defaults).forEach(([key, value]) => applyPreferenceUpdate({ key, value }));
};

// Microphone-based pitch scoring
async function _initMicScoring(songFilePath) {
  try {
    // Request mic permission
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: false }
    });

    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    window._pitchAnalyzer = new PitchAnalyzer(ctx, stream);

    // Initialize pitch meter UI
    const container = document.getElementById("pitch-meter-container");
    if (container) {
      window._pitchMeter = new PitchMeter(container);
      window._pitchMeter.reset();
      window._pitchMeter.show();
    }

    // Load reference pitch curve
    window._referencePitch = [];
    if (songFilePath) {
      try {
        const resp = await fetch("/pitch_data/" + encodeURIComponent(songFilePath));
        if (resp.ok) {
          window._referencePitch = await resp.json();
          console.log("Reference pitch loaded:", window._referencePitch.length, "points");
        }
      } catch (e) {
        console.log("No reference pitch available");
      }
    }

    // Start real-time analysis
    window._pitchAnalyzer.start((pitch, confidence) => {
      if (!window._pitchMeter) return;
      const video = getVideoPlayer();
      if (!video || video.paused) return;

      // Find reference pitch at current time
      const currentTime = video.currentTime;
      let refPitch = 0;
      if (window._referencePitch.length > 0) {
        // Binary search for closest time
        let lo = 0, hi = window._referencePitch.length - 1;
        while (lo < hi) {
          const mid = (lo + hi) >> 1;
          if (window._referencePitch[mid].time < currentTime) lo = mid + 1;
          else hi = mid;
        }
        if (lo < window._referencePitch.length) {
          const ref = window._referencePitch[lo];
          if (Math.abs(ref.time - currentTime) < 0.1 && ref.confidence > 0.3) {
            refPitch = ref.pitch;
          }
        }
      }

      window._pitchMeter.update(pitch, refPitch, confidence);
    });

    console.log("Mic scoring initialized");
  } catch (e) {
    console.log("Mic scoring unavailable:", e.message);
    // Silently fail — random scoring will be used as fallback
  }
}

const setupSocketEvents = () => {
  socket.on('connect', () => {
    console.log('Socket connected');
    socket.emit("register_splash");
    // Re-fetch now_playing state after reconnection
    $.get('/now_playing', function(data) {
      var np = JSON.parse(data);
      if (np && np.now_playing) {
        handleNowPlayingUpdate(np);
      }
    });
  });
  socket.on('splash_role', (role) => {
    isMaster = (role === "master");
    console.log("Splash role assigned:", role, isMaster ? "(Master active)" : "(Slave active - read-only)");
  });
  socket.on('connect_error', (error) => {
    console.error('Connection error:', error);
    flashNotification(PikaraokeConfig.translations.socketConnectionLost, "is-danger");
  });
  socket.on('disconnect', (reason) => {
    console.warn('Socket disconnected:', reason);
    flashNotification(PikaraokeConfig.translations.socketConnectionLost, "is-danger");
  });
  socket.on('pause', () => {
    const video = getVideoPlayer();
    const currVolume = video.volume;
    if (!video.paused) {
      $(video).animate({ volume: 0 }, 1000, () => {
        video.pause();
        video.volume = currVolume;
      });
    }
  });
  socket.on('play', () => {
    const video = getVideoPlayer();
    const currVolume = video.volume;
    if (video.paused) {
      video.play();
      video.volume = 0;
      $(video).animate({ volume: currVolume }, 1000);
    }
  });
  socket.on('skip', (reason) => {
    const video = getVideoPlayer();
    const currVolume = video.volume;
    if (isMediaPlaying(video)) {
      $(video).animate({ volume: 0 }, 1000, () => {
        video.pause();
        video.volume = currVolume;
        hideVideo();
      });
    } else {
      video.pause();
      hideVideo();
    }
  });
  socket.on('volume', (val) => {
    const video = getVideoPlayer();
    if (val === "up") {
      video.volume = Math.min(1, video.volume + 0.1);
    } else if (val === "down") {
      video.volume = Math.max(0, video.volume - 0.1);
    } else {
      video.volume = val;
    }
  });
  socket.on('restart', () => {
    const video = getVideoPlayer();
    video.currentTime = 0;
    if (video.paused) video.play();
  });
  socket.on("notification", (data) => {
    const notification = data.split("::");
    const message = notification[0];
    const categoryClass = notification.length > 1 ? notification[1] : "is-primary";
    flashNotification(message, categoryClass);
    if (isMaster) {
      socket.emit("clear_notification");
    }
  });
  socket.on("now_playing", handleNowPlayingUpdate);
  socket.on("preferences_update", applyPreferenceUpdate);
  socket.on("preferences_reset", applyPreferencesReset);
  socket.on("score_phrases_update", (phrases) => { scoreReviews = phrases; });

  socket.on("leaderboard", (data) => {
    const medals = ["1st", "2nd", "3rd"];
    const rows = data.map((entry, i) => {
      const rank = medals[i] || `${i + 1}.`;
      return `<tr><td>${rank}</td><td>${entry.singer}</td><td>${entry.avg} pts</td></tr>`;
    });
    $("#leaderboard-body").html(rows.join("") || "<tr><td colspan='3'>No scores yet.</td></tr>");
    $("#leaderboard-screen").fadeIn(500);
  });

  socket.on("hide_leaderboard", () => {
    $("#leaderboard-screen").fadeOut(400);
  });

  // Client-side pitch shift via SoundTouchJS AudioWorklet (no tempo change)
  socket.on("pitch_shift", async (semitones) => {
    const video = getVideoPlayer();
    if (!video) return;

    // Initialize audio context and SoundTouch worklet on first use
    if (!window._pitchShiftCtx) {
      if (_pitchShiftInitializing) return;
      _pitchShiftInitializing = true;
      try {
        window._pitchShiftCtx = new (window.AudioContext || window.webkitAudioContext)();
        await window._pitchShiftCtx.audioWorklet.addModule("/static/js/soundtouch-worklet.js");
        const source = window._pitchShiftCtx.createMediaElementSource(video);
        window._pitchShiftNode = new AudioWorkletNode(window._pitchShiftCtx, "soundtouch-processor");
        source.connect(window._pitchShiftNode);
        window._pitchShiftNode.connect(window._pitchShiftCtx.destination);
        console.log("SoundTouch AudioWorklet initialized");
      } catch (e) {
        console.warn("SoundTouch AudioWorklet failed:", e);
        flashNotification("此瀏覽器不支援即時升降 Key", "is-warning");
        window._pitchShiftCtx = null;
        _pitchShiftInitializing = false;
        return;
      }
      _pitchShiftInitializing = false;
    }

    // Resume context if suspended (requires user interaction)
    if (window._pitchShiftCtx.state === "suspended") {
      await window._pitchShiftCtx.resume();
    }

    // Set pitch shift via AudioParam (no tempo change)
    window._pitchShiftNode.parameters.get("pitchSemitones").value = semitones;
    console.log("Pitch shift: " + semitones + " semitones (SoundTouch, no tempo change)");
  });

  // Instant audio track switching (multi-audio HLS)
  socket.on("audio_mode_switch", (mode) => {
    if (!hlsInstance || !window.audioTrackMap) return;
    var trackIndex = window.audioTrackMap[mode];
    if (trackIndex !== undefined) {
      hlsInstance.audioTrack = trackIndex;
      // Force seeked event to re-enable SubtitlesOctopus timeupdate listener.
      // HLS audio track switch triggers seeking but not always seeked,
      // which permanently disables subtitle time sync.
      var video = getVideoPlayer();
      if (video) {
        setTimeout(function() {
          var pos = video.currentTime;
          video.currentTime = pos + 0.001;
          video.currentTime = pos;
        }, 150);
      }
      console.log("Audio track switched to: " + mode + " (index " + trackIndex + ")");
    }
  });

  socket.on("session_summary", (data) => {
    $("#summary-songs").text(data.total_songs || 0);
    var secs = data.elapsed_seconds || 0;
    var h = Math.floor(secs / 3600);
    var m = Math.floor((secs % 3600) / 60);
    $("#summary-duration").text(h > 0 ? h + "h " + m + "m" : m + " min");
    $("#summary-singers").text(data.total_singers || 0);
    if (data.most_active_singer) {
      $("#summary-mvp").text(data.most_active_singer);
      $("#summary-mvp-row").show();
    }
    if (data.top_scorer) {
      $("#summary-top-scorer").text(data.top_scorer);
      $("#summary-top-scorer-row").show();
    }
    if (data.most_played_song) {
      $("#summary-hit-song").text(data.most_played_song);
      $("#summary-hit-row").show();
    }
    $("#session-summary-screen").fadeIn(600);
    setTimeout(function() { $("#session-summary-screen").fadeOut(800); }, 12000);
  });

  socket.on("playback_position", (position) => {
    if (!isMaster) {
      const video = getVideoPlayer();
      if (isMediaPlaying(video)) {
        if (Math.abs(video.currentTime - position) > 2) {
          console.log("Slave drifting, syncing position to:", position);
          video.currentTime = position;
        }
      }
    }
  });
}

const handleSocketRecovery = () => {
  // A socket may disconnect if the tab is backgrounded for a while
  // Reconnect and configure event listeners when tab becomes visible again
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === 'visible') {
      autoplayConfirmed && loadNowPlaying();
      if (!socket.connected) {
        socket = io();
        setupSocketEvents();
      }
    }
  });
}

const setupUIScaling = () => {
  const urlParams = new URLSearchParams(window.location.search);
  const rawScale = urlParams.get('scale');
  if (!rawScale) return;
  uiScale = parseFloat(rawScale) || 1;

  const scaleTargets = [
    { selector: '#logo-container img.logo', origin: null },
    { selector: '#top-container', origin: 'top right' },
    { selector: '#ap-container', origin: 'top left' },
    { selector: '#qr-code', origin: 'bottom left' },
    { selector: '#up-next', origin: 'bottom right' },
    { selector: '#dvd', origin: null },
    { selector: '#your-score-text', origin: null },
    { selector: '#score-number-text', origin: null },
    { selector: '#score-review-text', origin: null },
    { selector: '#splash-notification', origin: 'top left' },
    { selector: '#clock', origin: 'top left' },
  ];

  scaleTargets.forEach(({ selector, origin }) => {
    const el = document.querySelector(selector);
    if (el) {
      el.style.transform = `scale(${uiScale})`;
      if (origin) el.style.transformOrigin = origin;
    }
  });
}

// Document ready procedures

$(function () {
  // Setup various features and listeners
  setupUIScaling();
  if (PikaraokeConfig.showSplashClock) startClock();
  setupScreensaver();
  setupOverlayMenus();
  setupVideoPlayer();
  setupBackgroundMusicPlayer();

  // Handle browser compatibility
  handleUnsupportedBrowser();
  testAutoplayCapability();
});


// Setup sockets and recovery outside of document ready to prevent race conditions
setupSocketEvents();
handleSocketRecovery();

// Fallback: if socket connected before listeners were attached, register now
if (socket.connected) {
  console.log('Socket already connected, registering splash...');
  socket.emit("register_splash");
}
