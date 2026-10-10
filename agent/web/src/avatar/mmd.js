// MMD adapter: the only place that knows MMD morph names and model files.
// The stage talks to it in abstract names (vowels, expression and motion names).
import { LoadAssetContainerAsync, Vector3 } from "@babylonjs/core";

// Side-effect import registers the .pmd scene loader plugin.
import "babylon-mmd/esm/Loader/pmdLoader";
// Registers the VMD runtime animation. Without it setRuntimeAnimation silently
// does nothing.
import "babylon-mmd/esm/Runtime/Animation/mmdRuntimeModelAnimation";

import { MmdAnimation } from "babylon-mmd/esm/Loader/Animation/mmdAnimation";
import { VmdLoader } from "babylon-mmd/esm/Loader/vmdLoader";
import { MmdStandardMaterialBuilder } from "babylon-mmd/esm/Loader/mmdStandardMaterialBuilder";
import { StreamAudioPlayer } from "babylon-mmd/esm/Runtime/Audio/streamAudioPlayer";
import { MmdRuntime } from "babylon-mmd/esm/Runtime/mmdRuntime";
import { MmdAmmoPhysics } from "babylon-mmd/esm/Runtime/Physics/mmdAmmoPhysics";
import { MmdAmmoJSPlugin } from "babylon-mmd/esm/Runtime/Physics/mmdAmmoJSPlugin";
import loadAmmo from "babylon-mmd/esm/Runtime/Physics/External/ammo.wasm";
import { approachMorphs, eyesClosed, mmdExpressionMorphs, mmdMouthMorphs } from "./mmdMorphs.js";
import { createMotionPlayer, findAudio } from "./mmdMotion.js";

// MMD authors its scenes at this gravity; Babylon's default is far too weak
// for MMD rigid bodies and the hair barely moves.
const GRAVITY = new Vector3(0, -98, 0);

// onMotionEnded(name) is called when a one-shot motion (a dance) is over,
// including when its files are missing.
export function createMmdAvatar(scene, { model = "/Miku.pmd", physics = true, onMotionEnded = () => {} } = {}) {
  let runtime = null;
  let mmdModel = null;
  let availableMorphs = new Set();
  // Expression morphs fade from face toward faceTarget every frame.
  let face = mmdExpressionMorphs("neutral");
  let faceTarget = face;
  let idle = null; // runtime animation handle of the idle loop
  // Set while a one-shot motion plays: mouth, blink and face are the VMD's then.
  let finishOneShot = null;

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
    scene.onBeforeRenderObservable.add(() => updateFace(scene.getEngine().getDeltaTime() / 1000));

    // MmdRuntime pauses at the end of the animation (with music: when the
    // music stops). Only the end counts; a pause mid-way is left alone.
    runtime.onPauseAnimationObservable.add(() => {
      if (runtime.currentFrameTime < runtime.animationFrameTimeDuration) return;
      if (finishOneShot) finishOneShot();
      else if (idle !== null) playFromStart();
    });
  }

  function playFromStart() {
    runtime.seekAnimation(0, true);
    runtime.playAnimation();
  }

  function updateFace(dt) {
    if (finishOneShot) return;
    face = approachMorphs(face, faceTarget, dt);
    for (const [name, weight] of Object.entries(face)) {
      if (availableMorphs.has(name)) mmdModel.morph.setMorphWeight(name, weight);
    }
  }

  // weights: {a, i, u, e, o}. Morph weights written here persist: the runtime
  // animation (idle motion) only writes morphs that have a track, and idle
  // motions are stripped of morph tracks (see applyIdle), so nothing overwrites them.
  function setMouth(weights) {
    if (!mmdModel || finishOneShot) return;
    for (const [name, weight] of Object.entries(mmdMouthMorphs(weights))) {
      if (availableMorphs.has(name)) mmdModel.morph.setMorphWeight(name, weight);
    }
  }

  function blink(weight) {
    if (finishOneShot) return;
    if (mmdModel && availableMorphs.has("まばたき")) mmdModel.morph.setMorphWeight("まばたき", weight);
  }

  // name: happy/sad/angry/surprised/relaxed/neutral. Fades in over ~0.2 s.
  function setExpression(name, weight = 1) {
    const target = mmdExpressionMorphs(name, weight);
    if (!target) {
      console.warn("mmd: unknown expression", name);
      return;
    }
    faceTarget = target;
  }

  // True while the face itself closes the eyes, so blinking should wait.
  function eyesShut() {
    return eyesClosed(face) || eyesClosed(faceTarget);
  }

  async function loadMotion(name, motion) {
    if (!mmdModel) throw new Error("model not loaded");
    const animation = await new VmdLoader(scene).loadAsync(name, motion.url);
    if (animation.endFrame <= 0) throw new Error("empty motion");
    const music = motion.music ? await findAudio(motion.music) : null;
    return { animation, music };
  }

  function applyMotion(name, loaded) {
    return name === "idle" ? applyIdle(loaded) : applyOneShot(loaded);
  }

  // Bones only: the VMD's morph tracks are dropped so it cannot override
  // setMouth / blink. (babylon-mmd's MmdModel.beforePhysics only calls
  // morph.resetMorphWeights() when replacing an already-set runtime animation,
  // and the runtime animation writes only morphs that have a track, so no
  // per-frame re-apply of mouth/blink weights is needed.)
  function applyIdle({ animation }) {
    const boneOnly = new MmdAnimation(
      animation.name,
      animation.boneTracks,
      animation.movableBoneTracks,
      [],
      animation.propertyTrack,
      animation.cameraTrack,
    );
    idle = mmdModel.createRuntimeAnimation(boneOnly);
    if (finishOneShot) return; // the one-shot puts the idle on when it ends
    mmdModel.setRuntimeAnimation(idle);
    playFromStart();
  }

  // The whole VMD, morphs included: during a dance the lip sync, blinking
  // and expressions are the VMD's. The music is synced by babylon-mmd's
  // audio player (the runtime follows the audio clock).
  async function applyOneShot({ animation, music }) {
    if (finishOneShot) throw new Error("another motion is playing");
    const handle = mmdModel.createRuntimeAnimation(animation);
    const player = new StreamAudioPlayer(scene);
    player.source = music;
    const finished = new Promise((resolve) => {
      finishOneShot = () => {
        finishOneShot = null;
        runtime.pauseAnimation();
        runtime.setAudioPlayer(null);
        player.dispose();
        mmdModel.setRuntimeAnimation(idle);
        mmdModel.destroyRuntimeAnimation(handle);
        mmdModel.morph.resetMorphWeights();
        face = mmdExpressionMorphs("neutral");
        faceTarget = face;
        runtime.seekAnimation(0, true);
        if (idle !== null) runtime.playAnimation();
        resolve();
      };
    });
    try {
      await runtime.setAudioPlayer(player);
      mmdModel.setRuntimeAnimation(handle);
      playFromStart();
    } catch (error) {
      finishOneShot();
      throw error;
    }
    return finished;
  }

  // Ends the one-shot motion now, as if it had played to the end (core's stop_motion).
  function stopMotion() {
    if (finishOneShot) finishOneShot();
  }

  // Motion files are optional; failures are logged once and never thrown.
  const motions = createMotionPlayer({ load: loadMotion, apply: applyMotion, ended: onMotionEnded });

  return { load, setMouth, blink, setExpression, eyesShut, playMotion: motions.playMotion, stopMotion };
}
