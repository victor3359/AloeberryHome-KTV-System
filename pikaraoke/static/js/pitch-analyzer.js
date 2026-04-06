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
    this.source = audioContext.createMediaStreamSource(stream);
    this.analyser = audioContext.createAnalyser();
    this.analyser.fftSize = 4096;
    this.source.connect(this.analyser);

    this.buffer = new Float32Array(this.analyser.fftSize);
    this.running = false;
    this.callback = null;
    this.sampleRate = audioContext.sampleRate;
  }

  start(callback) {
    this.callback = callback;
    this.running = true;
    this._loop();
  }

  stop() {
    this.running = false;
    this.source.disconnect();
  }

  _loop() {
    if (!this.running) return;
    this.analyser.getFloatTimeDomainData(this.buffer);
    const result = this._detectPitchYIN(this.buffer, this.sampleRate);
    if (this.callback) {
      this.callback(result.pitch, result.confidence);
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
    const yinBuffer = new Float32Array(halfLen);

    // Step 1: Difference function
    for (let tau = 0; tau < halfLen; tau++) {
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
    for (let tau = 1; tau < halfLen; tau++) {
      runningSum += yinBuffer[tau];
      yinBuffer[tau] *= tau / runningSum;
    }

    // Step 3: Absolute threshold
    let tauEstimate = -1;
    for (let tau = 2; tau < halfLen; tau++) {
      if (yinBuffer[tau] < threshold) {
        while (tau + 1 < halfLen && yinBuffer[tau + 1] < yinBuffer[tau]) {
          tau++;
        }
        tauEstimate = tau;
        break;
      }
    }

    if (tauEstimate === -1) {
      return { pitch: -1, confidence: 0 };
    }

    // Step 4: Parabolic interpolation for better precision
    let betterTau = tauEstimate;
    if (tauEstimate > 0 && tauEstimate < halfLen - 1) {
      const s0 = yinBuffer[tauEstimate - 1];
      const s1 = yinBuffer[tauEstimate];
      const s2 = yinBuffer[tauEstimate + 1];
      betterTau = tauEstimate + (s0 - s2) / (2 * (s0 - 2 * s1 + s2));
    }

    const pitch = sampleRate / betterTau;
    const confidence = 1 - yinBuffer[tauEstimate];

    // Filter out unreasonable frequencies (human voice: 80-1100 Hz)
    if (pitch < 80 || pitch > 1100) {
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
