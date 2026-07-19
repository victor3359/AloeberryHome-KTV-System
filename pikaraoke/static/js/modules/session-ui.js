// Self-contained UI helpers for the splash screen: text formatters, the toast notifier, the
// digital clock, and the session-elapsed timer. Each owns its own state; library globals ($ /
// PikaraokeConfig / document) resolve from module scope as usual.

export const formatElapsed = (s) => {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  return `${m}:${String(sec).padStart(2, "0")}`;
};

export const formatTime = (seconds) => {
  if (isNaN(seconds)) {
    return "00:00";
  }
  const totalSeconds = Math.floor(seconds);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const secs = totalSeconds % 60;
  const formattedMinutes = String(minutes).padStart(2, "0");
  const formattedSeconds = String(secs).padStart(2, "0");
  return `${formattedMinutes}:${formattedSeconds}`;
};

// Escape user/song-controlled text before injecting via .html(). Song titles come from YouTube
// filenames and singer names from a free-text phone prompt, so both are untrusted.
export const escapeHtml = (s) =>
  String(s == null ? "" : s).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );

export const flashNotification = (message, categoryClass) => {
  const $ = window.jQuery;
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
};

let _clockIntervalId = null;

export const startClock = () => {
  if (_clockIntervalId) return;
  const update = () => {
    const el = document.getElementById("clock");
    if (el)
      el.textContent = new Date().toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        hour12: true,
      });
  };
  update();
  _clockIntervalId = setInterval(update, 1000);
};

export const stopClock = () => {
  if (!_clockIntervalId) return;
  clearInterval(_clockIntervalId);
  _clockIntervalId = null;
};

let _sessionElapsedBase = 0;
let _sessionElapsedTimerId = null;

export const startSessionTimer = (base) => {
  _sessionElapsedBase = base;
  if (_sessionElapsedTimerId) clearInterval(_sessionElapsedTimerId);
  const el = document.getElementById("session-elapsed-display");
  if (el) el.textContent = formatElapsed(_sessionElapsedBase);
  document.getElementById("session-timer").style.display = "";
  _sessionElapsedTimerId = setInterval(() => {
    _sessionElapsedBase++;
    if (el) el.textContent = formatElapsed(_sessionElapsedBase);
  }, 1000);
};
