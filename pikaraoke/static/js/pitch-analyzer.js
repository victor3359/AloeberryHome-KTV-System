/**
 * YIN Pitch Detection Algorithm for real-time vocal scoring.
 * Detects fundamental frequency (F0) from audio data.
 *
 * Usage:
 *   const analyzer = new PitchAnalyzer(audioContext, micStream);
 *   analyzer.start((pitch, confidence) => { ... });
 *   analyzer.stop();
 */

class PitchAnalyzer {
  constructor(audioContext, stream) {
    this.audioContext = audioContext;
    this.stream = stream;
    this.source = audioContext.createMediaStreamSource(stream);
    this.analyser = audioContext.createAnalyser();
    this.analyser.fftSize = 4096;
    this.source.connect(this.analyser);

    this.buffer = new Float32Array(this.analyser.fftSize);
    this.running = false;
    this.callback = null;
    this.sampleRate = audioContext.sampleRate;
  }

  start(callback, shouldAnalyze) {
    this.callback = callback;
    // Optional predicate; when it returns false (e.g. video paused) detection is skipped so the
    // O(window*tau) YIN does not run while nothing is being sung.
    this.shouldAnalyze = shouldAnalyze || null;
    this.running = true;
    this._lastDetect = 0;
    this._loop();
  }

  stop() {
    this.running = false;
    this.source.disconnect();
    // Release the mic capture and the AudioContext. stop() previously only disconnected the
    // source node, leaking one live getUserMedia stream + AudioContext per song (a long session
    // stacked dozens, saturating the TV CPU and never releasing the OS mic indicator).
    if (this.stream) {
      this.stream.getTracks().forEach((track) => track.stop());
    }
    if (this.audioContext && this.audioContext.state !== "closed") {
      this.audioContext.close().catch(() => {});
    }
  }

  _loop() {
    if (!this.running) return;
    // Throttle detection to ~20/s (the reference curve is 20 Hz and the meter CSS transition is
    // 0.1s, so faster gains nothing) and skip it entirely when inactive. Running the YIN on every
    // 60fps frame burned ~a full core on the TV main thread alongside HLS decode + libass.
    const now = performance.now();
    const active = !this.shouldAnalyze || this.shouldAnalyze();
    if (active && now - this._lastDetect >= 45) {
      this._lastDetect = now;
      this.analyser.getFloatTimeDomainData(this.buffer);
      const result = this._detectPitchYIN(this.buffer, this.sampleRate);
      if (this.callback) {
        this.callback(result.pitch, result.confidence);
      }
    }
    requestAnimationFrame(() => this._loop());
  }

  /**
   * YIN algorithm for fundamental frequency estimation.
   * Returns { pitch: Hz or -1, confidence: 0-1 }
   */
  _detectPitchYIN(buffer, sampleRate) {
    const threshold = 0.15;
    const halfLen = Math.floor(buffer.length / 2);
    // Only search taus in the 80-1100 Hz vocal band. A full [1, halfLen) scan (~2048 for fftSize
    // 4096) is ~3x the work for taus that could never be a scored pitch.
    const tauMin = Math.max(2, Math.floor(sampleRate / 1100));
    const tauMax = Math.min(halfLen - 1, Math.ceil(sampleRate / 80));
    const yinBuffer = new Float32Array(tauMax + 1);

    // Step 1: Difference function (up to tauMax only)
    for (let tau = 0; tau <= tauMax; tau++) {
      let sum = 0;
      for (let i = 0; i < halfLen; i++) {
        const delta = buffer[i] - buffer[i + tau];
        sum += delta * delta;
      }
      yinBuffer[tau] = sum;
    }

    // Step 2: Cumulative mean normalized difference
    yinBuffer[0] = 1;
    let runningSum = 0;
    for (let tau = 1; tau <= tauMax; tau++) {
      runningSum += yinBuffer[tau];
      yinBuffer[tau] *= tau / runningSum;
    }

    // Step 3: Absolute threshold, within the band
    let tauEstimate = -1;
    for (let tau = tauMin; tau <= tauMax; tau++) {
      if (yinBuffer[tau] < threshold) {
        while (tau + 1 <= tauMax && yinBuffer[tau + 1] < yinBuffer[tau]) {
          tau++;
        }
        tauEstimate = tau;
        break;
      }
    }

    if (tauEstimate === -1) {
      return { pitch: -1, confidence: 0 };
    }

    // Step 4: Parabolic interpolation, guarding the degenerate (flat) denominator that made
    // betterTau — and therefore pitch — NaN.
    let betterTau = tauEstimate;
    if (tauEstimate > tauMin && tauEstimate < tauMax) {
      const s0 = yinBuffer[tauEstimate - 1];
      const s1 = yinBuffer[tauEstimate];
      const s2 = yinBuffer[tauEstimate + 1];
      const denom = 2 * (s0 - 2 * s1 + s2);
      if (denom !== 0) {
        betterTau = tauEstimate + (s0 - s2) / denom;
      }
    }

    const pitch = sampleRate / betterTau;
    const confidence = 1 - yinBuffer[tauEstimate];

    // Reject non-finite or out-of-band pitch. Without the isFinite check a NaN passed the
    // comparison (NaN < 80 and NaN > 1100 are both false) and froze the meter at "NaN%".
    if (!Number.isFinite(pitch) || pitch < 80 || pitch > 1100) {
      return { pitch: -1, confidence: 0 };
    }

    return { pitch, confidence };
  }

  /**
   * Convert frequency to MIDI note number.
   */
  static freqToMidi(freq) {
    if (freq <= 0) return -1;
    return 69 + 12 * Math.log2(freq / 440);
  }

  /**
   * Convert MIDI note to frequency.
   */
  static midiToFreq(midi) {
    return 440 * Math.pow(2, (midi - 69) / 12);
  }

  /**
   * Calculate cents difference between two frequencies.
   */
  static centsDiff(f1, f2) {
    if (f1 <= 0 || f2 <= 0) return Infinity;
    return 1200 * Math.log2(f1 / f2);
  }
}

// Export for use in splash.js
if (typeof window !== "undefined") {
  window.PitchAnalyzer = PitchAnalyzer;
}
