// Plays `speak` messages one at a time and drives the mouth from the viseme
// timeline, using AudioContext.currentTime as the clock.
import { approach, targetVowel, targetWeights } from "./visemes.js";

const SILENT = targetWeights("closed");

export function base64ToArrayBuffer(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

export function createSpeech({ audioContext, send, setMouth, decodeBase64 = base64ToArrayBuffer }) {
  const queue = [];
  let playing = null; // { msg, startTime }
  let busy = false; // true from dequeue until the clip ended (or failed)
  let current = SILENT;

  async function playNext() {
    if (busy || queue.length === 0) return;
    busy = true;
    const msg = queue.shift();
    let buffer;
    try {
      buffer = await audioContext.decodeAudioData(decodeBase64(msg.wav));
    } catch (error) {
      // Still report the end so core's half-duplex does not stall.
      console.error("speech: decode failed", error);
      send({ type: "speak_ended", id: msg.id });
      busy = false;
      playNext();
      return;
    }
    const source = audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(audioContext.destination);
    source.onended = () => {
      playing = null;
      busy = false;
      send({ type: "speak_ended", id: msg.id });
      playNext();
    };
    const startTime = audioContext.currentTime;
    playing = { msg, startTime };
    source.start(startTime);
    send({ type: "speak_started", id: msg.id });
  }

  function enqueue(msg) {
    queue.push(msg);
    playNext();
  }

  function update(dt) {
    const target = playing
      ? targetWeights(targetVowel(playing.msg.visemes ?? [], audioContext.currentTime - playing.startTime))
      : SILENT;
    current = approach(current, target, dt);
    setMouth(current);
  }

  return { enqueue, update };
}
