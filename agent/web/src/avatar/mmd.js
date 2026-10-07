// MMD adapter: the only place that knows MMD morph names and model files.
// The stage talks to it in abstract names (vowels, expression and motion names).
import { LoadAssetContainerAsync, Vector3 } from "@babylonjs/core";

// Side-effect import registers the .pmd scene loader plugin.
import "babylon-mmd/esm/Loader/pmdLoader";
// Registers the VMD runtime animation. Without it setRuntimeAnimation silently
// does nothing (see src/dance.js).
import "babylon-mmd/esm/Runtime/Animation/mmdRuntimeModelAnimation";

import { MmdAnimation } from "babylon-mmd/esm/Loader/Animation/mmdAnimation";
import { VmdLoader } from "babylon-mmd/esm/Loader/vmdLoader";
import { MmdStandardMaterialBuilder } from "babylon-mmd/esm/Loader/mmdStandardMaterialBuilder";
import { MmdRuntime } from "babylon-mmd/esm/Runtime/mmdRuntime";
import { MmdAmmoPhysics } from "babylon-mmd/esm/Runtime/Physics/mmdAmmoPhysics";
import { MmdAmmoJSPlugin } from "babylon-mmd/esm/Runtime/Physics/mmdAmmoJSPlugin";
import loadAmmo from "babylon-mmd/esm/Runtime/Physics/External/ammo.wasm";
import { mmdMouthMorphs } from "./mmdMorphs.js";
import { createMotionPlayer } from "./mmdMotion.js";

// MMD authors its scenes at this gravity; Babylon's default is far too weak
// for MMD rigid bodies and the hair barely moves.
const GRAVITY = new Vector3(0, -98, 0);

export function createMmdAvatar(scene, { model = "/Miku.pmd", physics = true } = {}) {
  let runtime = null;
  let mmdModel = null;
  let availableMorphs = new Set();

  async function buildPhysics() {
    if (!physics) return null;
    const ammo = await loadAmmo();
    scene.enablePhysics(GRAVITY, new MmdAmmoJSPlugin(true, ammo));
    return new MmdAmmoPhysics(scene);
  }

  async function load() {
    runtime = new MmdRuntime(scene, await buildPhysics());
    runtime.register(scene);

    const container = await LoadAssetContainerAsync(model, scene, {
      // babylon-mmd leaves SharedMaterialBuilder null for tree-shaking. Skip this
      // and every material silently comes out as Babylon's default grey.
      pluginOptions: { mmdmodel: { materialBuilder: new MmdStandardMaterialBuilder() } },
    });
    container.addAllToScene();

    const rootMesh = container.meshes.find((mesh) => mesh.metadata?.isMmdModel) ?? container.meshes[0];
    mmdModel = runtime.createMmdModel(rootMesh);
    availableMorphs = new Set(mmdModel.morph.morphs.map((m) => m.name));
  }

  // weights: {a, i, u, e, o}. Morph weights written here persist: the runtime
  // animation (idle motion) only writes morphs that have a track, and idle
  // motions are stripped of morph tracks (see applyIdle), so nothing overwrites them.
  function setMouth(weights) {
    if (!mmdModel) return;
    for (const [name, weight] of Object.entries(mmdMouthMorphs(weights))) {
      if (availableMorphs.has(name)) mmdModel.morph.setMorphWeight(name, weight);
    }
  }

  function blink(weight) {
    if (mmdModel && availableMorphs.has("まばたき")) mmdModel.morph.setMorphWeight("まばたき", weight);
  }

  // No-op until expressions land (#24).
  function setExpression(_name, _weight) {}

  // Bones only: the VMD's morph tracks are dropped so it cannot override
  // setMouth / blink. (babylon-mmd's MmdModel.beforePhysics only calls
  // morph.resetMorphWeights() when replacing an already-set runtime animation,
  // and the runtime animation writes only morphs that have a track, so no
  // per-frame re-apply of mouth/blink weights is needed.)
  function applyIdle(animation) {
    const boneOnly = new MmdAnimation(
      animation.name,
      animation.boneTracks,
      animation.movableBoneTracks,
      [],
      animation.propertyTrack,
      animation.cameraTrack,
    );
    if (!mmdModel) throw new Error("model not loaded");
    if (boneOnly.endFrame <= 0) throw new Error("empty motion");
    mmdModel.setRuntimeAnimation(mmdModel.createRuntimeAnimation(boneOnly));
    // MmdRuntime pauses at the end of the animation; rewind and play for a loop.
    runtime.onPauseAnimationObservable.add(() => {
      if (runtime.currentFrameTime < boneOnly.endFrame) return;
      runtime.seekAnimation(0, true);
      runtime.playAnimation();
    });
    runtime.seekAnimation(0, true);
    runtime.playAnimation();
  }

  // Motion files are optional; failures are logged once and never thrown.
  const motions = createMotionPlayer({
    load: (url) => new VmdLoader(scene).loadAsync("idle", url),
    apply: applyIdle,
  });

  return { load, setMouth, blink, setExpression, playMotion: motions.playMotion };
}
