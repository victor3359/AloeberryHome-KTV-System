// Microphone-based pitch scoring. Owns the per-song analyzer, meter, and reference-pitch curve —
// state that used to live on window and be shared implicitly with the player. player-core drives it
// (startMicScoring per song, stopMicScoring on skip/end) and reads the final score via getMicScore().
// Splash injects only the #video accessor; the pitch primitives are imported directly.

import { PitchAnalyzer } from "/static/js/pitch-analyzer.js";
import { PitchMeter } from "/static/js/pitch-meter.js";

let _analyzer = null;
let _meter = null;
let _referencePitch = [];
let d = {}; // { getVideoPlayer }

export function initMicScoring(deps) {
  d = deps;
}

export function stopMicScoring() {
  // Stop + release the current analyzer (PitchAnalyzer.stop stops the mic tracks and closes its
  // AudioContext). Safe to call when none is active.
  if (_analyzer) {
    _analyzer.stop();
    _analyzer = null;
  }
}

export function hideMeter() {
  if (_meter) _meter.hide();
}

export function getMicScore() {
  // The mic score (0-100) for the song just sung, or undefined if the meter never gathered enough
  // frames (mic denied / too short) — the caller then falls back to a random score. Resets the
  // meter so the next singer starts clean.
  if (_meter && _meter.totalFrames > 10) {
    const score = _meter.getScore();
    _meter.reset();
    return score;
  }
  return undefined;
}

export async function startMicScoring(songFilePath) {
  // Release the previous song's analyzer first — a skip or mid-song url change re-inits without
  // going through endSong, so without this the old mic stream + AudioContext + rAF loop leak.
  stopMicScoring();
  // Clear stale frames from the previous song's meter BEFORE this song scores. _meter is only
  // replaced when init succeeds, so if getUserMedia fails below, the old meter would otherwise
  // survive and endSong would record the previous singer's score for this singer.
  if (_meter) _meter.reset();
  try {
    // Request mic permission
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: false },
    });

    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    _analyzer = new PitchAnalyzer(ctx, stream);

    // Initialize pitch meter UI
    const container = document.getElementById("pitch-meter-container");
    if (container) {
      _meter = new PitchMeter(container);
      _meter.reset();
      _meter.show();
    }

    // Load reference pitch curve
    _referencePitch = [];
    if (songFilePath) {
      try {
        const resp = await fetch("/pitch_data/" + encodeURIComponent(songFilePath));
        if (resp.ok) {
          _referencePitch = await resp.json();
          console.log("Reference pitch loaded:", _referencePitch.length, "points");
        }
      } catch (e) {
        console.log("No reference pitch available");
      }
    }

    // Start real-time analysis
    _analyzer.start(
      (pitch, confidence) => {
        if (!_meter) return;
        const video = d.getVideoPlayer();
        if (!video || video.paused) return;

        // Find reference pitch at current time
        const currentTime = video.currentTime;
        let refPitch = 0;
        if (_referencePitch.length > 0) {
          // Binary search for closest time
          let lo = 0,
            hi = _referencePitch.length - 1;
          while (lo < hi) {
            const mid = (lo + hi) >> 1;
            if (_referencePitch[mid].time < currentTime) lo = mid + 1;
            else hi = mid;
          }
          if (lo < _referencePitch.length) {
            const ref = _referencePitch[lo];
            if (Math.abs(ref.time - currentTime) < 0.1 && ref.confidence > 0.3) {
              refPitch = ref.pitch;
            }
          }
        }

        _meter.update(pitch, refPitch, confidence);
      },
      () => {
        // Skip the YIN entirely while the video is paused — nothing is being sung.
        const v = d.getVideoPlayer();
        return !!(v && !v.paused);
      }
    );

    console.log("Mic scoring initialized");
  } catch (e) {
    console.log("Mic scoring unavailable:", e.message);
    // Silently fail — random scoring will be used as fallback
  }
}
