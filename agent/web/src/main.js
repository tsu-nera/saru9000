// Renders the あにまさ式 Miku model in the browser and plays a VMD dance.
//
// Replaces what MMDAgent did natively in C++ (see docs/browser-mmd-viewer.md).
// Assets are not committed; place them under public/ per web/README.md.
import {
  Engine,
  Scene,
  ArcRotateCamera,
  HemisphericLight,
  DirectionalLight,
  Vector3,
  Color3,
  Color4,
  LoadAssetContainerAsync,
} from "@babylonjs/core";

// Side-effect imports register the .pmd scene loader plugin and the VMD
// animation runtime. Without the latter, setRuntimeAnimation silently does
// nothing.
import "babylon-mmd/esm/Loader/pmdLoader";
import "babylon-mmd/esm/Runtime/Animation/mmdRuntimeModelAnimation";

import { MmdStandardMaterialBuilder } from "babylon-mmd/esm/Loader/mmdStandardMaterialBuilder";
import { MmdRuntime } from "babylon-mmd/esm/Runtime/mmdRuntime";
import { VmdLoader } from "babylon-mmd/esm/Loader/vmdLoader";
import { MmdAmmoPhysics } from "babylon-mmd/esm/Runtime/Physics/mmdAmmoPhysics";
import { MmdAmmoJSPlugin } from "babylon-mmd/esm/Runtime/Physics/mmdAmmoJSPlugin";
import loadAmmo from "babylon-mmd/esm/Runtime/Physics/External/ammo.wasm";

const params = new URLSearchParams(location.search);
const CONFIG = {
  model: params.get("model") ?? "/Miku.pmd",
  motion: params.get("motion") ?? "/mikumiku.vmd",
  // ?nophysics=1 drops the solver — useful to see what the hair and necktie
  // would look like without it.
  physics: !params.has("nophysics"),
  // MMD authors its scenes at this gravity; Babylon's default is far too weak
  // for MMD rigid bodies and the hair barely moves.
  gravity: new Vector3(0, -98, 0),
};

const hud = document.getElementById("hud");
const canvas = document.getElementById("stage");
const controls = document.getElementById("controls");
const playPause = document.getElementById("playPause");
const seek = document.getElementById("seek");

const lines = [];
function log(message) {
  lines.push(message);
  hud.textContent = lines.join("\n");
}

function fail(error) {
  console.error(error);
  hud.classList.add("error");
  log("ERROR: " + (error?.message ?? String(error)));
}

const engine = new Engine(canvas, true);
const scene = new Scene(engine);
scene.clearColor = new Color4(0.13, 0.13, 0.19, 1);
scene.ambientColor = new Color3(0.5, 0.5, 0.5);

const camera = new ArcRotateCamera("camera", -Math.PI / 2, Math.PI / 2.15, 30, new Vector3(0, 9, 0), scene);
camera.attachControl(canvas, true);
camera.lowerRadiusLimit = 5;
camera.upperRadiusLimit = 80;
camera.wheelDeltaPercentage = 0.02;

new HemisphericLight("hemisphere", new Vector3(0, 1, 0), scene).intensity = 0.7;
new DirectionalLight("directional", new Vector3(0.5, -1, 1), scene).intensity = 0.8;

async function buildPhysics() {
  if (!CONFIG.physics) {
    log("physics: disabled");
    return null;
  }
  const ammo = await loadAmmo();
  scene.enablePhysics(CONFIG.gravity, new MmdAmmoJSPlugin(true, ammo));
  log("physics: " + scene.getPhysicsEngine().getPhysicsPluginName());
  return new MmdAmmoPhysics(scene);
}

async function loadModel(runtime) {
  const container = await LoadAssetContainerAsync(CONFIG.model, scene, {
    // babylon-mmd leaves SharedMaterialBuilder null for tree-shaking. Skip this
    // and every material silently comes out as Babylon's default grey.
    pluginOptions: { mmdmodel: { materialBuilder: new MmdStandardMaterialBuilder() } },
  });
  container.addAllToScene();

  const rootMesh = container.meshes.find((mesh) => mesh.metadata?.isMmdModel) ?? container.meshes[0];
  // createMmdModel trims the metadata, so read the physics counts first.
  const { rigidBodies = [], joints = [] } = rootMesh.metadata ?? {};

  const model = runtime.createMmdModel(rootMesh);
  const skeleton = container.skeletons[0];
  log(`model: ${skeleton.bones.length} bones / ${model.morph.morphs.length} morphs`);
  log(`physics data: ${rigidBodies.length} rigid bodies / ${joints.length} joints`);
  return model;
}

async function loadMotion(model) {
  const animation = await new VmdLoader(scene).loadAsync("motion", CONFIG.motion);
  model.setRuntimeAnimation(model.createRuntimeAnimation(animation));
  return animation;
}

function wireControls(runtime, endFrame) {
  seek.max = String(Math.ceil(endFrame));
  controls.hidden = false;

  playPause.addEventListener("click", () => {
    if (runtime.isAnimationPlaying) {
      runtime.pauseAnimation();
      playPause.textContent = "▶ 再生";
    } else {
      runtime.playAnimation();
      playPause.textContent = "⏸ 一時停止";
    }
  });

  let scrubbing = false;
  seek.addEventListener("pointerdown", () => (scrubbing = true));
  seek.addEventListener("pointerup", () => (scrubbing = false));
  seek.addEventListener("input", () => runtime.seekAnimation(Number(seek.value), true));

  scene.onBeforeRenderObservable.add(() => {
    if (!scrubbing) seek.value = String(Math.floor(runtime.currentFrameTime));
  });
}

try {
  const physics = await buildPhysics();
  const runtime = new MmdRuntime(scene, physics);
  runtime.register(scene);

  const model = await loadModel(runtime);
  const animation = await loadMotion(model);

  const endFrame = animation.endFrame ?? 0;
  log(`motion: ${Math.round(endFrame)} frames (${(endFrame / 30).toFixed(1)}s)`);

  runtime.seekAnimation(0, true);
  runtime.playAnimation();
  wireControls(runtime, endFrame);

  // handy for poking at the scene from devtools
  Object.assign(window, { scene, model, runtime });
} catch (error) {
  fail(error);
}

engine.runRenderLoop(() => scene.render());
addEventListener("resize", () => engine.resize());
