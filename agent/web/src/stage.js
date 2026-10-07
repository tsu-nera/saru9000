// Entry of the stage page: renders the avatar, plays core's speech and
// lip-syncs it. See README.md.
import {
  Engine,
  Scene,
  ArcRotateCamera,
  HemisphericLight,
  DirectionalLight,
  Vector3,
  Color3,
  Color4,
} from "@babylonjs/core";
import { createBlinker } from "./idle.js";
import { createMmdAvatar } from "./avatar/mmd.js";
import { createProtocol } from "./protocol.js";
import { createSpeech } from "./speech.js";

const params = new URLSearchParams(location.search);

const canvas = document.getElementById("stage");
const hudState = document.getElementById("hudState");
const hudUtterance = document.getElementById("hudUtterance");
const hudError = document.getElementById("hudError");
const overlay = document.getElementById("overlay");
const sayInput = document.getElementById("say");

function fail(error) {
  console.error(error);
  hudError.textContent += "ERROR: " + (error?.message ?? String(error)) + "\n";
}

const engine = new Engine(canvas, true);
const scene = new Scene(engine);
scene.clearColor = new Color4(0.13, 0.13, 0.19, 1);
scene.ambientColor = new Color3(0.5, 0.5, 0.5);

// Framed on the face; the model is ~20 units tall.
const camera = new ArcRotateCamera("camera", -Math.PI / 2, Math.PI / 2.15, 8, new Vector3(0, 17, 0), scene);
camera.attachControl(canvas, true);
camera.lowerRadiusLimit = 2;
camera.upperRadiusLimit = 60;
camera.wheelDeltaPercentage = 0.02;

new HemisphericLight("hemisphere", new Vector3(0, 1, 0), scene).intensity = 0.7;
new DirectionalLight("directional", new Vector3(0.5, -1, 1), scene).intensity = 0.8;

const avatar = createMmdAvatar(scene, {
  model: params.get("model") ?? "/Miku.pmd",
  physics: !params.has("nophysics"),
});

const audioContext = new AudioContext();
if (params.has("autoplay")) {
  overlay.hidden = true;
} else {
  overlay.addEventListener("click", () => {
    audioContext.resume();
    overlay.hidden = true;
  });
}

// `protocol` is assigned below; the speech callbacks only run after that.
const speech = createSpeech({
  audioContext,
  send: (obj) => protocol.send(obj),
  setMouth: (weights) => avatar.setMouth(weights),
});
const protocol = createProtocol({
  url: `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws?role=stage`,
  handlers: {
    speak: (msg) => speech.enqueue(msg),
    state: (msg) => (hudState.textContent = `state: ${msg.state}`),
    utterance: (msg) => (hudUtterance.textContent = `${msg.who}: ${msg.text}`),
    expression: (msg) => avatar.setExpression(msg.name, 1),
    motion: (msg) => avatar.playMotion(msg.name),
  },
});

sayInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.isComposing) return;
  const text = sayInput.value.trim();
  if (!text) return;
  protocol.send({ type: "text_input", text });
  sayInput.value = "";
});

scene.onBeforeRenderObservable.add(() => speech.update(engine.getDeltaTime() / 1000));

Object.assign(window, { scene, avatar, protocol });

try {
  await avatar.load();
  const blinker = createBlinker({ setBlink: (weight) => avatar.blink(weight) });
  scene.onBeforeRenderObservable.add(() => blinker.update(engine.getDeltaTime() / 1000));
  // Never rejects: a missing idle.vmd just logs one line.
  avatar.playMotion("idle");
} catch (error) {
  fail(error);
}

engine.runRenderLoop(() => scene.render());
addEventListener("resize", () => engine.resize());
