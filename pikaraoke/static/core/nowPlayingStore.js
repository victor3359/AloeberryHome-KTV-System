// Single source of truth for the now-playing state.
// Owns the "now_playing" socket subscription and the /now_playing HTTP fetch so
// individual pages don't each fetch/parse it. ES module, consumed at runtime.
//
// Re-wires its socket listener on every subscribe(): the socket is a shared
// singleton and another page (queueview) clears its now_playing listeners with a
// blunt socket.off("now_playing"), so the store must defensively re-bind. The
// handler reference is passed to off()/on() so it never double-binds.
let _state = null;
const _subs = new Map(); // key -> callback

function _emit() {
  _subs.forEach(function (cb) {
    try {
      cb(_state);
    } catch (e) {
      /* one bad subscriber must not break the others */
    }
  });
}

function _onNowPlaying(np) {
  // socket payload is an already-parsed object
  _state = np;
  _emit();
}

function _wireSocket() {
  const getSocket = window.getSocket;
  const socket = getSocket && getSocket();
  if (!socket) {
    return;
  }
  socket.off("now_playing", _onNowPlaying);
  socket.on("now_playing", _onNowPlaying);
}

export function refresh() {
  const $ = window.jQuery;
  if (!$) {
    return;
  }
  $.get("/now_playing", function (data) {
    try {
      _state = typeof data === "string" ? JSON.parse(data) : data;
      _emit();
    } catch (e) {
      /* ignore malformed payloads */
    }
  });
}

export function subscribe(key, cb) {
  _subs.set(key, cb);
  _wireSocket();
  if (_state) {
    try {
      cb(_state);
    } catch (e) {
      /* ignore */
    }
  } else {
    refresh();
  }
}

export function getState() {
  return _state;
}
