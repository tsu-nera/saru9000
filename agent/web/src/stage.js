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
import { fetchJson, loadConfig } from "./config.js";
import { createBlinker } from "./idle.js";
import { createMmdAvatar } from "./avatar/mmd.js";
import { createProtocol } from "./protocol.js";
import { createScreen } from "./screen.js";
import { createSpeech } from "./speech.js";

const params = new URLSearchParams(location.search);

const canvas = document.getElementById("stage");
const hudState = document.getElementById("hudState");
const hudMode = document.getElementById("hudMode");
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

let config;
try {
  config = await loadConfig(fetchJson, params);
} catch (error) {
  fail(error);
  throw error;
}

// Faces the model from the front. elevation is degrees above the horizontal;
// Babylon's beta is measured down from the vertical axis.
const camera = new ArcRotateCamera(
  "camera",
  -Math.PI / 2,
  ((90 - config.camera.elevation) * Math.PI) / 180,
  config.camera.distance,
  new Vector3(0, config.camera.height, 0),
  scene,
);
camera.attachControl(canvas, true);
camera.lowerRadiusLimit = 2;
camera.upperRadiusLimit = 60;
camera.wheelDeltaPercentage = 0.02;

new HemisphericLight("hemisphere", new Vector3(0, 1, 0), scene).intensity = 0.7;
new DirectionalLight("directional", new Vector3(0.5, -1, 1), scene).intensity = 0.8;

const screen = createScreen(scene, { enabled: config.screen?.enabled ?? true });

const avatar = createMmdAvatar(scene, {
  model: params.get("model") ?? "/Miku.pmd",
  physics: !params.has("nophysics"),
  // `protocol` is assigned below; motions only end after that.
  onMotionEnded: (name) => protocol.send({ type: "motion_ended", name }),
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
  setExpression: (name) => avatar.setExpression(name, 1),
});
const MODE_LABELS = { wake: "wake（呼びかけ）", always: "always（常時）" };
let listenMode = null;
const protocol = createProtocol({
  url: `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws?role=stage`,
  handlers: {
    speak: (msg) => speech.enqueue(msg),
    state: (msg) => (hudState.textContent = `state: ${msg.state}`),
    utterance: (msg) => (hudUtterance.textContent = `${msg.name ?? msg.who}: ${msg.text}`),
    expression: (msg) => avatar.setExpression(msg.name, 1),
    listen_mode: (msg) => {
      listenMode = msg.mode;
      hudMode.textContent = `mode: ${MODE_LABELS[msg.mode] ?? msg.mode}`;
    },
    motion: (msg) => avatar.playMotion(msg.name),
    stop_motion: () => avatar.stopMotion(),
    log: (msg) => screen.add(msg),
  },
});

// The label changes when the core confirms with a listen_mode.
hudMode.addEventListener("click", () => {
  if (listenMode === null) return;
  protocol.send({ type: "listen_mode", mode: listenMode === "wake" ? "always" : "wake" });
});

sayInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.isComposing) return;
  const text = sayInput.value.trim();
  if (!text) return;
  protocol.send({ type: "text_input", text });
  sayInput.value = "";
});

// L shows or hides the log screen; not saved.
addEventListener("keydown", (event) => {
  if (event.key !== "l" && event.key !== "L") return;
  if (event.isComposing || event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
  screen.toggle();
});

scene.onBeforeRenderObservable.add(() => speech.update(engine.getDeltaTime() / 1000));

Object.assign(window, { scene, avatar, protocol, screen });

try {
  await avatar.load();
  const blinker = createBlinker({ setBlink: (weight) => avatar.blink(weight), paused: () => avatar.eyesShut() });
  scene.onBeforeRenderObservable.add(() => blinker.update(engine.getDeltaTime() / 1000));
  // Never rejects: a missing idle.vmd just logs one line.
  avatar.playMotion("idle");
} catch (error) {
  fail(error);
}

engine.runRenderLoop(() => scene.render());
addEventListener("resize", () => engine.resize());
