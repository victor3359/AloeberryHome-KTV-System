// Unified user-facing notifications.
// Replaces the duplicated showNotification (base.html + spa-navigation.js).
// Reads window.jQuery at call time; no-ops gracefully when the node is absent
// (blank pages such as the splash screen have no #notification-alt).

const NOTIFICATION_SELECTOR = "#notification-alt";

export function notify(message, categoryClass, timeout = 3000) {
  const $ = window.jQuery;
  if (!$) {
    return;
  }
  const node = $(NOTIFICATION_SELECTOR);
  if (node.length === 0) {
    return;
  }
  node.addClass(categoryClass);
  node.find("div").text(message);
  node.fadeIn();
  setTimeout(function () {
    node.fadeOut();
  }, timeout);
  setTimeout(function () {
    node.removeClass(categoryClass);
  }, timeout + 750);
}
