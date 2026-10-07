import { describe, expect, it } from "vitest";
import { createSpeech } from "./speech.js";

function fakeAudioContext() {
  const sources = [];
  return {
    sources,
    currentTime: 0,
    destination: {},
    decodeAudioData: async () => ({}),
    createBufferSource() {
      const source = { connect() {}, start() {}, onended: null };
      sources.push(source);
      return source;
    },
  };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("createSpeech expression", () => {
  it("applies speak.expression when the clip starts, and only then", async () => {
    const audioContext = fakeAudioContext();
    const sent = [];
    const faces = [];
    const speech = createSpeech({
      audioContext,
      send: (msg) => sent.push(msg),
      setMouth: () => {},
      setExpression: (name) => faces.push(name),
      decodeBase64: () => new ArrayBuffer(0),
    });
    speech.enqueue({ id: 1, wav: "", visemes: [], expression: "happy" });
    speech.enqueue({ id: 2, wav: "", visemes: [], expression: "sad" });
    speech.enqueue({ id: 3, wav: "", visemes: [] });
    await flush();
    expect(faces).toEqual(["happy"]);
    audioContext.sources[0].onended();
    await flush();
    expect(faces).toEqual(["happy", "sad"]);
    audioContext.sources[1].onended();
    await flush();
    expect(faces).toEqual(["happy", "sad"]);
    expect(sent.map((m) => m.type)).toEqual([
      "speak_started",
      "speak_ended",
      "speak_started",
      "speak_ended",
      "speak_started",
    ]);
  });
});
