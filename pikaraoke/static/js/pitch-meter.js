/**
 * Real-time pitch accuracy meter for KTV scoring.
 * Shows a visual indicator of how close the singer's pitch matches the reference.
 *
 * Usage:
 *   const meter = new PitchMeter(containerElement);
 *   meter.update(detectedPitch, referencePitch, confidence);
 *   meter.getScore(); // 0-100
 */

class PitchMeter {
  constructor(container) {
    this.container = container;
    this.matchedFrames = 0;
    this.totalFrames = 0;
    this.tolerance = 100; // cents (±1 semitone)
    this._createUI();
  }

  _createUI() {
    this.container.innerHTML = `
      <div id="pitch-meter" style="
        position: absolute; right: 20px; top: 50%; transform: translateY(-50%);
        width: 8px; height: 200px; background: rgba(255,255,255,0.1);
        border-radius: 4px; z-index: 4; display: none;
      ">
        <div id="pitch-indicator" style="
          position: absolute; left: -4px; width: 16px; height: 16px;
          border-radius: 50%; background: #10b981;
          transition: bottom 0.1s ease, background 0.1s ease;
          bottom: 50%;
        "></div>
        <div id="pitch-target" style="
          position: absolute; left: -2px; width: 12px; height: 4px;
          border-radius: 2px; background: rgba(255,255,255,0.3);
          bottom: 50%;
        "></div>
      </div>
      <div id="pitch-score-live" style="
        position: absolute; right: 10px; bottom: 60px;
        font-size: 1.2rem; font-weight: 700; color: #06b6d4;
        z-index: 4; display: none;
      ">0%</div>
    `;
  }

  show() {
    const meter = document.getElementById("pitch-meter");
    const score = document.getElementById("pitch-score-live");
    if (meter) meter.style.display = "block";
    if (score) score.style.display = "block";
  }

  hide() {
    const meter = document.getElementById("pitch-meter");
    const score = document.getElementById("pitch-score-live");
    if (meter) meter.style.display = "none";
    if (score) score.style.display = "none";
  }

  /**
   * Update the pitch meter with current detected and reference pitches.
   * @param {number} detected - Detected pitch in Hz (-1 if no voice)
   * @param {number} reference - Expected pitch in Hz (0 if no reference at this time)
   * @param {number} confidence - Detection confidence 0-1
   */
  update(detected, reference, confidence) {
    const indicator = document.getElementById("pitch-indicator");
    const target = document.getElementById("pitch-target");
    if (!indicator || !target) return;

    // No reference at this point (instrumental section)
    if (!reference || reference <= 0) {
      indicator.style.opacity = "0.3";
      return;
    }

    indicator.style.opacity = "1";

    // No voice detected
    if (detected <= 0 || confidence < 0.3) {
      indicator.style.background = "#ef4444"; // Red
      this.totalFrames++;
      this._updateScore();
      return;
    }

    // Calculate cents difference
    const cents = PitchAnalyzer.centsDiff(detected, reference);
    const absCents = Math.abs(cents);

    // Score this frame
    this.totalFrames++;
    if (absCents <= this.tolerance) {
      this.matchedFrames++;
    }

    // Visual position (map cents to pixel offset, ±400 cents = full range)
    const normalizedOffset = Math.max(-1, Math.min(1, cents / 400));
    const bottomPercent = 50 + normalizedOffset * 40; // 10% to 90%
    indicator.style.bottom = bottomPercent + "%";

    // Color based on accuracy
    if (absCents <= 50) {
      indicator.style.background = "#10b981"; // Green — excellent
    } else if (absCents <= 100) {
      indicator.style.background = "#f59e0b"; // Yellow — close
    } else {
      indicator.style.background = "#ef4444"; // Red — off
    }

    this._updateScore();
  }

  _updateScore() {
    const scoreEl = document.getElementById("pitch-score-live");
    if (scoreEl && this.totalFrames > 0) {
      const pct = Math.round((this.matchedFrames / this.totalFrames) * 100);
      scoreEl.textContent = pct + "%";
    }
  }

  /**
   * Get the final score (0-100).
   */
  getScore() {
    if (this.totalFrames === 0) return 0;
    return Math.round((this.matchedFrames / this.totalFrames) * 100);
  }

  /**
   * Reset for a new song.
   */
  reset() {
    this.matchedFrames = 0;
    this.totalFrames = 0;
    const scoreEl = document.getElementById("pitch-score-live");
    if (scoreEl) scoreEl.textContent = "0%";
    const indicator = document.getElementById("pitch-indicator");
    if (indicator) indicator.style.bottom = "50%";
  }
}

if (typeof window !== "undefined") {
  window.PitchMeter = PitchMeter;
}
