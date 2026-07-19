// Client-side pitch shift via SoundTouchJS AudioWorklet (no tempo change).
//
// The graph is built ONCE and kept for the entire session. An HTMLMediaElement can be captured
// by only one MediaElementSourceNode, and after that capture its audio is permanently routed
// through the graph — closing the context (an earlier per-song cleanup) left #video feeding a
// dead graph, muting every song after the first use of 升降Key. At 0 semitones we bypass the
// worklet (source -> destination) so unshifted playback keeps native latency; the worklet is
// spliced in only while actually shifting.
//
// Dependencies (video element + a notifier) are injected via initPitchShift so this module owns
// no splash globals.

let _ctx = null;
let _source = null;
let _node = null;
let _bypassed = true;
let _initializing = false;

let _getVideoPlayer = () => null;
let _flashNotification = () => {};

export function initPitchShift({ getVideoPlayer, flashNotification }) {
  _getVideoPlayer = getVideoPlayer;
  _flashNotification = flashNotification;
}

async function _ensureGraph() {
  if (_ctx) return true;
  if (_initializing) return false;
  _initializing = true;
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    await ctx.audioWorklet.addModule("/static/js/soundtouch-worklet.js");
    const source = ctx.createMediaElementSource(_getVideoPlayer());
    const node = new AudioWorkletNode(ctx, "soundtouch-processor");
    source.connect(ctx.destination); // start bypassed: 0 semitones == native passthrough
    _ctx = ctx;
    _source = source;
    _node = node;
    _bypassed = true;
    console.log("SoundTouch AudioWorklet initialized");
    return true;
  } catch (e) {
    console.warn("SoundTouch AudioWorklet failed:", e);
    _flashNotification("此瀏覽器不支援即時升降 Key", "is-warning");
    _ctx = null;
    return false;
  } finally {
    _initializing = false;
  }
}

// Splice the worklet in/out and set the pitch. Never tears down the capture.
function _route(semitones) {
  if (!_ctx || !_source || !_node) return;
  if (semitones === 0) {
    if (!_bypassed) {
      _source.disconnect();
      _node.disconnect();
      _source.connect(_ctx.destination);
      _bypassed = true;
    }
  } else {
    if (_bypassed) {
      _source.disconnect();
      _source.connect(_node);
      _node.connect(_ctx.destination);
      _bypassed = false;
    }
    _node.parameters.get("pitchSemitones").value = semitones;
  }
}

// Reset to native pitch on song change / endSong WITHOUT destroying the persistent graph.
export function resetPitchShift() {
  _route(0);
}

// Handle a pitch_shift socket event. Builds the persistent graph on first real shift; a 0 with
// no graph is a no-op.
export async function applyPitchShift(semitones) {
  if (!_getVideoPlayer()) return;
  if (semitones !== 0) {
    if (!(await _ensureGraph())) return;
  } else if (!_ctx) {
    return;
  }
  if (_ctx.state === "suspended") {
    await _ctx.resume();
  }
  _route(semitones);
  console.log("Pitch shift: " + semitones + " semitones (SoundTouch, no tempo change)");
}
