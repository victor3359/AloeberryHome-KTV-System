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
    }
    return _socket;
  }

  window.getSocket = getSocket;
})();
