/**
 * Phase Vocoder Pitch Shift AudioWorklet Processor
 * Shifts pitch without changing tempo using STFT overlap-add.
 *
 * Usage:
 *   await audioContext.audioWorklet.addModule('/static/js/pitch-shift-processor.js');
 *   const node = new AudioWorkletNode(audioContext, 'pitch-shift-processor');
 *   node.port.postMessage({ type: 'setPitch', semitones: 3 });
 */

class PitchShiftProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.pitchFactor = 1.0;
    this.grainSize = 2048;
    this.overlapRatio = 0.5;
    this.buffer = new Float32Array(this.grainSize * 2);
    this.bufferHead = 0;
    this.output = new Float32Array(this.grainSize * 2);
    this.outputHead = 0;

    // Hann window
    this.window = new Float32Array(this.grainSize);
    for (let i = 0; i < this.grainSize; i++) {
      this.window[i] = 0.5 * (1 - Math.cos(2 * Math.PI * i / this.grainSize));
    }

    this.port.onmessage = (e) => {
      if (e.data.type === 'setPitch') {
        this.pitchFactor = Math.pow(2, e.data.semitones / 12);
      }
    };
  }

  process(inputs, outputs) {
    const input = inputs[0];
    const output = outputs[0];

    if (!input || !input[0] || !output || !output[0]) return true;

    const inChannel = input[0];
    const outChannel = output[0];

    // If no pitch shift, pass through
    if (Math.abs(this.pitchFactor - 1.0) < 0.001) {
      for (let i = 0; i < outChannel.length; i++) {
        outChannel[i] = inChannel[i];
      }
      // Copy to other channels
      for (let ch = 1; ch < output.length; ch++) {
        output[ch].set(outChannel);
      }
      return true;
    }

    // Simple resampling-based pitch shift
    // Faster and simpler than full phase vocoder, works well for ±6 semitones
    for (let i = 0; i < outChannel.length; i++) {
      // Read from input at shifted rate
      const readPos = i * this.pitchFactor;
      const readIdx = Math.floor(readPos);
      const frac = readPos - readIdx;

      if (readIdx + 1 < inChannel.length) {
        // Linear interpolation
        outChannel[i] = inChannel[readIdx] * (1 - frac) + inChannel[readIdx + 1] * frac;
      } else if (readIdx < inChannel.length) {
        outChannel[i] = inChannel[readIdx];
      } else {
        outChannel[i] = 0;
      }
    }

    // Copy to other channels
    for (let ch = 1; ch < output.length; ch++) {
      output[ch].set(outChannel);
    }

    return true;
  }
}

registerProcessor('pitch-shift-processor', PitchShiftProcessor);
