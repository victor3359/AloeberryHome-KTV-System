// Player-core + sync: the splash controller's runtime heart. Owns the now-playing lifecycle state
// (socket, nowPlaying, currentVideoUrl, isMaster, volume) and wires every socket event. Delegates
// to the extracted feature modules (imported directly) and to a few splash-local helpers +
// shared-state accessors injected via initPlayerCore: mic scoring, the #video element, the
// screensaver's idle counter, autoplay confirmation, and the ?scale UI factor.

import { updateBackgroundMediaState } from "/static/js/modules/bg-media.js";
import { startScore, setScoreReviews } from "/static/score.js";
import { resetPitchShift, applyPitchShift } from "/static/js/modules/pitch-shift.js";
import {
  formatTime,
  escapeHtml,
  flashNotification,
  startSessionTimer,
} from "/static/js/modules/session-ui.js";
import { updateSubtitles } from "/static/js/modules/subtitles.js";
import { setupHls, destroyHls, switchAudioTrack } from "/static/js/modules/audio-pipeline.js";
import {
  startMicScoring,
  stopMicScoring,
  getMicScore,
  hideMeter,
} from "/static/js/modules/mic-scoring.js";

let socket = io();
let nowPlaying = {};
let currentVideoUrl = null;
let isMaster = false;
let volume = 0.85;
const playbackStartTimeout = 10000;

let d = {}; // injected splash-local deps + shared-state accessors

export function getNowPlaying() {
  return nowPlaying;
}

const endSong = async (reason = null, showScore = false) => {
  // Stop mic scoring (PitchAnalyzer.stop releases the mic stream + AudioContext)
  stopMicScoring();
  hideMeter();

  // Reset pitch to native for the next song. The pitch-shift graph persists for the whole session
  // (see resetPitchShift): #video can be captured only once, so closing the context would leave it
  // routed into a dead graph and mute every later song.
  resetPitchShift();

  if (showScore && !PikaraokeConfig.disableScore) {
    const singer = nowPlaying.now_playing_user;
    const song = nowPlaying.now_playing;

    // Use the mic-based score if the meter gathered enough frames, otherwise random.
    let scoreValue = getMicScore();
    if (scoreValue === undefined) {
      scoreValue = await startScore("/static/");
    } else {
      await startScore("/static/", scoreValue);
    }
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
    var delay = PikaraokeConfig.splashDelay || 2;
    var remaining = delay;
    $("#transition-countdown").text("Starting in " + remaining + "s...");
    if (window._transCountdown) clearInterval(window._transCountdown);
    window._transCountdown = setInterval(function () {
      remaining--;
      if (remaining > 0) {
        $("#transition-countdown").text("Starting in " + remaining + "s...");
      } else {
        $("#transition-countdown").text("Preparing...");
        clearInterval(window._transCountdown);
      }
    }, 1000);
  }
  destroyHls();
  const video = d.getVideoPlayer();
  video.pause();
  $("#video-source").attr("src", "");
  video.load();
  d.hideVideo();
  if (isMaster) {
    socket.emit("end_song", reason);
  } else {
    console.log("Slave active (read-only): skipping end_song emission");
  }
};

const handleNowPlayingUpdate = (np) => {
  nowPlaying = np;
  if (np.now_playing) {
    let nowPlayingHtml = `<span>${escapeHtml(np.now_playing)}</span> `;
    if (np.now_playing_transpose !== 0) {
      nowPlayingHtml += `<span class='is-size-6 has-text-success'><b>Key</b>: ${d.getSemitonesLabel(np.now_playing_transpose)} </span>`;
    }
    $("#now-playing-song").html(nowPlayingHtml);
    const singerLabel = np.now_playing_user2
      ? `${escapeHtml(np.now_playing_user)} &amp; ${escapeHtml(np.now_playing_user2)}`
      : escapeHtml(np.now_playing_user);
    $("#now-playing-singer").html(singerLabel);
    $("#now-playing").fadeIn();
  } else {
    $("#now-playing").fadeOut();
  }
  if (np.up_next) {
    $("#up-next-song").html(escapeHtml(np.up_next));
    const nextSingerLabel = np.next_user2
      ? `${escapeHtml(np.next_user)} &amp; ${escapeHtml(np.next_user2)}`
      : escapeHtml(np.next_user);
    $("#up-next-singer").html(nextSingerLabel);
    $("#up-next").fadeIn();
  } else {
    $("#up-next").fadeOut();
  }

  if (np.session_elapsed !== undefined) {
    startSessionTimer(np.session_elapsed);
  }

  if (np.now_playing || np.up_next) {
    d.resetIdle();
  }
  updateBackgroundMediaState();

  const video = d.getVideoPlayer();

  // Subtitles (SubtitlesOctopus/libass) — owned by modules/subtitles.js.
  updateSubtitles(np, video, d.getUiScale());

  if (!np.now_playing_url) {
    $("#progress-bar-container").hide();
    $("#progress-bar-fill").css("width", "0%");
    if (!np.up_next) {
      $("#transition-screen").fadeOut(400, function () {
        this.classList.remove("transition-enter-active");
      });
    }
  }

  if (np.now_playing_url && np.now_playing_url !== currentVideoUrl) {
    // Reset pitch to native for the new song; keep the persistent graph (see resetPitchShift).
    resetPitchShift();

    $("#transition-screen").fadeOut(400, function () {
      this.classList.remove("transition-enter-active");
    });
    $("#progress-bar-fill").css({ width: "0%", transition: "none" });
    $("#progress-bar-container").show();
    setTimeout(function () {
      $("#progress-bar-fill").css("transition", "width 0.8s linear");
    }, 3000);
    currentVideoUrl = np.now_playing_url;
    const streamUrl = np.now_playing_url;
    $("#video-source").attr("src", "");
    video.load();
    $("#video-source").attr("src", streamUrl);

    if (streamUrl.endsWith(".m3u8")) {
      setupHls(streamUrl, video, d.browser);
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

    video.play().catch((err) => {
      console.error("Play failed:", err);
      setTimeout(() => video.play(), 1000);
    });

    // Initialize mic-based pitch scoring (if not disabled)
    if (!PikaraokeConfig.disableScore) {
      startMicScoring(np.now_playing_filename || "");
    }

    if (np.now_playing_position && d.isMediaPlaying(video)) {
      if (Math.abs(video.currentTime - np.now_playing_position) > 2) {
        console.log("Syncing to server position:", np.now_playing_position);
        video.currentTime = np.now_playing_position;
      }
    }

    setTimeout(() => {
      if (!d.isMediaPlaying(video) && !video.paused) {
        endSong("failed to start");
      }
    }, playbackStartTimeout);
  }
};

async function loadNowPlaying() {
  const data = await $.get("/now_playing");
  handleNowPlayingUpdate(JSON.parse(data));
}

const setupVideoPlayer = () => {
  $("#video-container").hide();
  const video = d.getVideoPlayer();
  video.addEventListener("play", () => {
    $("#video-container").show();
    if (isMaster) {
      setTimeout(() => {
        socket.emit("start_song");
      }, 1200);
    }
  });

  // Master reports playback position to server
  setInterval(() => {
    if (isMaster && d.isMediaPlaying(video)) {
      socket.emit("playback_position", video.currentTime);
    }
  }, 1000);

  video.addEventListener("ended", () => {
    endSong("complete", true);
  });
  video.addEventListener("timeupdate", (e) => {
    $("#current").text(formatTime(video.currentTime));
    const duration = video.duration || nowPlaying.now_playing_duration;
    if (duration > 0 && video.currentTime > 2) {
      $("#progress-bar-fill").css("width", (video.currentTime / duration) * 100 + "%");
    }
  });
  $("#video source")[0].addEventListener("error", (e) => {
    if (d.isMediaPlaying(video)) {
      endSong("error while playing");
    }
  });
  window.addEventListener(
    "beforeunload",
    function (event) {
      if (d.isMediaPlaying(video)) {
        endSong("splash screen closed");
      }
    },
    true
  );
};

const setupSocketEvents = () => {
  // Idempotent: drop any handlers from a prior setup before (re)binding. handleSocketRecovery
  // re-invokes this on visibilitychange and io() returns the same multiplexed socket, so without
  // this every handler — including 'connect' -> register_splash — would stack a duplicate. The
  // second register_splash from the same sid makes the server reply 'slave', demoting the only TV
  // so it stops emitting end_song and the queue stalls when a song finishes.
  socket.off();
  socket.on("connect", () => {
    console.log("Socket connected");
    socket.emit("register_splash");
    // Re-fetch now_playing state after reconnection
    $.get("/now_playing", function (data) {
      var np = JSON.parse(data);
      if (np && np.now_playing) {
        handleNowPlayingUpdate(np);
      }
    });
  });
  socket.on("splash_role", (role) => {
    isMaster = role === "master";
    console.log("Splash role assigned:", role, isMaster ? "(Master active)" : "(Slave active - read-only)");
  });
  socket.on("connect_error", (error) => {
    console.error("Connection error:", error);
    flashNotification(PikaraokeConfig.translations.socketConnectionLost, "is-danger");
  });
  socket.on("disconnect", (reason) => {
    console.warn("Socket disconnected:", reason);
    flashNotification(PikaraokeConfig.translations.socketConnectionLost, "is-danger");
  });
  socket.on("pause", () => {
    const video = d.getVideoPlayer();
    const currVolume = video.volume;
    if (!video.paused) {
      $(video).animate({ volume: 0 }, 1000, () => {
        video.pause();
        video.volume = currVolume;
      });
    }
  });
  socket.on("play", () => {
    const video = d.getVideoPlayer();
    const currVolume = video.volume;
    if (video.paused) {
      video.play();
      video.volume = 0;
      $(video).animate({ volume: currVolume }, 1000);
    }
  });
  socket.on("skip", (reason) => {
    // Skip pauses without going through endSong, so release the analyzer here too.
    stopMicScoring();
    hideMeter();
    const video = d.getVideoPlayer();
    const currVolume = video.volume;
    if (d.isMediaPlaying(video)) {
      $(video).animate({ volume: 0 }, 1000, () => {
        video.pause();
        video.volume = currVolume;
        d.hideVideo();
      });
    } else {
      video.pause();
      d.hideVideo();
    }
  });
  socket.on("volume", (val) => {
    const video = d.getVideoPlayer();
    if (val === "up") {
      video.volume = Math.min(1, video.volume + 0.1);
    } else if (val === "down") {
      video.volume = Math.max(0, video.volume - 0.1);
    } else {
      video.volume = val;
    }
  });
  socket.on("restart", () => {
    const video = d.getVideoPlayer();
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
  socket.on("preferences_update", d.applyPreferenceUpdate);
  socket.on("preferences_reset", d.applyPreferencesReset);
  socket.on("score_phrases_update", (phrases) => {
    setScoreReviews(phrases);
  });

  socket.on("leaderboard", (data) => {
    const medals = ["1st", "2nd", "3rd"];
    const rows = data.map((entry, i) => {
      const rank = medals[i] || `${i + 1}.`;
      return `<tr><td>${rank}</td><td>${escapeHtml(entry.singer)}</td><td>${entry.avg} pts</td></tr>`;
    });
    $("#leaderboard-body").html(rows.join("") || "<tr><td colspan='3'>No scores yet.</td></tr>");
    $("#leaderboard-screen").fadeIn(500);
  });

  socket.on("hide_leaderboard", () => {
    $("#leaderboard-screen").fadeOut(400);
  });

  // Client-side pitch shift via SoundTouchJS AudioWorklet (no tempo change)
  socket.on("pitch_shift", applyPitchShift);

  // Instant audio track switching (multi-audio HLS)
  socket.on("audio_mode_switch", (mode) => switchAudioTrack(mode, d.getVideoPlayer()));

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
    setTimeout(function () {
      $("#session-summary-screen").fadeOut(800);
    }, 12000);
  });

  socket.on("playback_position", (position) => {
    if (!isMaster) {
      const video = d.getVideoPlayer();
      if (d.isMediaPlaying(video)) {
        if (Math.abs(video.currentTime - position) > 2) {
          console.log("Slave drifting, syncing position to:", position);
          video.currentTime = position;
        }
      }
    }
  });
};

const handleSocketRecovery = () => {
  // A socket may disconnect if the tab is backgrounded for a while. Reconnect and re-configure
  // listeners when the tab becomes visible again.
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") {
      d.getAutoplayConfirmed() && loadNowPlaying();
      if (!socket.connected) {
        socket = io();
        setupSocketEvents();
      }
    }
  });
};

export function initPlayerCore(deps) {
  d = deps;
  // Setup sockets and recovery immediately (outside document ready) to prevent race conditions.
  setupSocketEvents();
  handleSocketRecovery();
  // Fallback: if the socket connected before listeners were attached, register now.
  if (socket.connected) {
    console.log("Socket already connected, registering splash...");
    socket.emit("register_splash");
  }
  return { handleNowPlayingUpdate, loadNowPlaying, setupVideoPlayer, getNowPlaying };
}
