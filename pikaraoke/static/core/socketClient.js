// Single shared Socket.IO connection for the whole app.
// Replaces the per-page io() calls scattered across the templates so that one
// long-lived connection is reused across SPA navigations.
//
// This is a CLASSIC script (not an ES module): page scripts call getSocket() at
// parse time, before deferred module bootstraps run, so the global must be
// defined synchronously in the document head. The socket.io client library is
// loaded as a classic <script> before this file, providing the global `io`.
(function () {
  var _socket = null;

  function getSocket() {
    if (typeof io === "undefined") {
      return null;
    }
    if (!_socket) {
      _socket = io();
      // Server-restart handshake: the server announces a per-boot id on connect. This page is
      // long-lived (living-room remote left open for days); when the id changes the server was
      // restarted — likely with updated code — so reload to shed stale JavaScript. The shared
      // window state keeps a same-boot reconnect (wifi blip) from ever looking like a restart.
      _socket.on("server_hello", function (id) {
        if (window.__pikaraokeServerId === undefined) {
          window.__pikaraokeServerId = id;
        } else if (window.__pikaraokeServerId !== id) {
          window.location.reload();
        }
      });
    }
    return _socket;
  }

  window.getSocket = getSocket;
})();
