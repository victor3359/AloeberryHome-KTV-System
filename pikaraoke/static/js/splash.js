import { startScreensaver, stopScreensaver } from "/static/screensaver.js";
import { getBackgroundMusicPlayer, playBGMusic, playBGVideo, shouldBackgroundMediaPlay, updateBackgroundMediaState, setupBackgroundMusicPlayer, initBgMedia } from "/static/js/modules/bg-media.js";
import { PitchAnalyzer } from "/static/js/pitch-analyzer.js";
import { PitchMeter } from "/static/js/pitch-meter.js";
import { initPitchShift } from "/static/js/modules/pitch-shift.js";
import { flashNotification, startClock, stopClock } from "/static/js/modules/session-ui.js";
import { createPreferences } from "/static/js/modules/preferences.js";
import { initPlayerCore } from "/static/js/modules/player-core.js";

// The player-core controller (sockets + now-playing lifecycle), assigned once initPlayerCore runs
// below. splash.js is now the composition root: it wires the feature modules and owns only the
// permissions / screensaver / overlay-menu / mic-scoring / ui-scaling concerns.
let player;
let mouseTimer = null;
let cursorVisible = false;
let showMenu = false;
let menuButtonVisible = false;
let autoplayConfirmed = false;
let idleTime = 0;
let screensaverTimeoutSeconds = PikaraokeConfig.screensaverTimeout;
let uiScale = null;

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

// Wire bg-media's injected accessors. getNowPlaying resolves through the player-core controller
// once assigned (all callers run at runtime, after initPlayerCore below).
initBgMedia({
  getNowPlaying: () => (player ? player.getNowPlaying() : {}),
  getAutoplayConfirmed: () => autoplayConfirmed,
  isMediaPlaying,
});

// Inject the pitch-shift module's deps lazily (getVideoPlayer/flashNotification are defined below).
initPitchShift({
  getVideoPlayer: () => getVideoPlayer(),
  flashNotification: (m, c) => flashNotification(m, c),
});

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
  player.loadNowPlaying();
};
window.handleConfirmation = handleConfirmation;

const hideVideo = () => {
  $("#video-container").hide();
}

const getVideoPlayer = () => $("#video")[0]

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
          startScreensaver();
        }
        if (idleTime > screensaverTimeoutSeconds + 36000) idleTime = screensaverTimeoutSeconds;
      } else {
        if (screensaver.style.visibility === 'visible') {
          screensaver.style.visibility = 'hidden';
          stopScreensaver();
          updateBackgroundMediaState(true);
        }
      }
      idleTime++;
    }, 1000)
  }
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

// Preference effects fan out to bg-media, the session clock, the video, the screensaver timeout,
// and the theme — assembled here as the modularization's last registry via injected deps.
const { applyPreferenceUpdate, applyPreferencesReset } = createPreferences({
  playBGVideo,
  playBGMusic,
  shouldBackgroundMediaPlay,
  getBackgroundMusicPlayer,
  startClock,
  stopClock,
  getVideoPlayer,
  isMediaPlaying,
  setScreensaverTimeout: (v) => {
    screensaverTimeoutSeconds = v;
  },
});

// Microphone-based pitch scoring
function stopMicScoring() {
  // Stop + release the current analyzer (PitchAnalyzer.stop stops the mic tracks and closes its
  // AudioContext). Safe to call when none is active.
  if (window._pitchAnalyzer) {
    window._pitchAnalyzer.stop();
    window._pitchAnalyzer = null;
  }
}

async function _initMicScoring(songFilePath) {
  // Release the previous song's analyzer first — a skip or mid-song url change re-inits without
  // going through endSong, so without this the old mic stream + AudioContext + rAF loop leak.
  stopMicScoring();
  // Clear stale frames from the previous song's meter BEFORE this song scores. window._pitchMeter
  // is only replaced when init succeeds, so if getUserMedia fails below, the old meter would
  // otherwise survive and endSong would record the previous singer's score for this singer.
  if (window._pitchMeter) window._pitchMeter.reset();
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
    }, () => {
      // Skip the YIN entirely while the video is paused — nothing is being sung.
      const v = getVideoPlayer();
      return !!(v && !v.paused);
    });

    console.log("Mic scoring initialized");
  } catch (e) {
    console.log("Mic scoring unavailable:", e.message);
    // Silently fail — random scoring will be used as fallback
  }
}

// Initialize the player-core controller: it owns the now-playing lifecycle + all socket wiring and
// runs setupSocketEvents immediately (outside document ready), matching the original ordering. All
// its deps are defined above; the video-element / idle-counter / autoplay / ui-scale accessors are
// injected so the shared state stays here.
player = initPlayerCore({
  getVideoPlayer,
  isMediaPlaying,
  hideVideo,
  stopMicScoring,
  initMicScoring: _initMicScoring,
  browser: { isChrome, isEdge, isMobileSafari },
  getAutoplayConfirmed: () => autoplayConfirmed,
  resetIdle: () => {
    idleTime = 0;
  },
  getUiScale: () => uiScale,
  applyPreferenceUpdate,
  applyPreferencesReset,
});

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
  player.setupVideoPlayer();
  setupBackgroundMusicPlayer();

  // Handle browser compatibility
  handleUnsupportedBrowser();
  testAutoplayCapability();
});
