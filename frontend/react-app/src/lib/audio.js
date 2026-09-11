export function floatTo16BitPCM(float32Array) {
  const buffer = new ArrayBuffer(float32Array.length * 2);
  const view = new DataView(buffer);
  for (let index = 0; index < float32Array.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, float32Array[index]));
    view.setInt16(index * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return buffer;
}

export function downsampleBuffer(buffer, sampleRate, outputSampleRate) {
  if (outputSampleRate === sampleRate || outputSampleRate > sampleRate) return buffer;
  const ratio = sampleRate / outputSampleRate;
  const result = new Float32Array(Math.round(buffer.length / ratio));
  let inputOffset = 0;
  for (let outputOffset = 0; outputOffset < result.length; outputOffset += 1) {
    const nextInputOffset = Math.round((outputOffset + 1) * ratio);
    let total = 0;
    let count = 0;
    for (let index = inputOffset; index < nextInputOffset && index < buffer.length; index += 1) {
      total += buffer[index];
      count += 1;
    }
    result[outputOffset] = count ? total / count : 0;
    inputOffset = nextInputOffset;
  }
  return result;
}

export function encodeAudioChunk(float32Array, sampleRate) {
  const pcm = new Uint8Array(floatTo16BitPCM(downsampleBuffer(float32Array, sampleRate, 16000)));
  let binary = "";
  for (let index = 0; index < pcm.length; index += 0x8000) binary += String.fromCharCode(...pcm.subarray(index, index + 0x8000));
  return btoa(binary);
}
