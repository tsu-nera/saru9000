// MMD adapter: the only place that knows MMD morph names and model files.
// The stage talks to it in abstract names (vowels, expression and motion names).
import { LoadAssetContainerAsync, Vector3 } from "@babylonjs/core";

// Side-effect import registers the .pmd scene loader plugin.
import "babylon-mmd/esm/Loader/pmdLoader";

import { MmdStandardMaterialBuilder } from "babylon-mmd/esm/Loader/mmdStandardMaterialBuilder";
import { MmdRuntime } from "babylon-mmd/esm/Runtime/mmdRuntime";
import { MmdAmmoPhysics } from "babylon-mmd/esm/Runtime/Physics/mmdAmmoPhysics";
import { MmdAmmoJSPlugin } from "babylon-mmd/esm/Runtime/Physics/mmdAmmoJSPlugin";
import loadAmmo from "babylon-mmd/esm/Runtime/Physics/External/ammo.wasm";
import { mmdMouthMorphs } from "./mmdMorphs.js";

// MMD authors its scenes at this gravity; Babylon's default is far too weak
// for MMD rigid bodies and the hair barely moves.
const GRAVITY = new Vector3(0, -98, 0);

export function createMmdAvatar(scene, { model = "/Miku.pmd", physics = true } = {}) {
  let mmdModel = null;
  let availableMorphs = new Set();

  async function buildPhysics() {
    if (!physics) return null;
    const ammo = await loadAmmo();
    scene.enablePhysics(GRAVITY, new MmdAmmoJSPlugin(true, ammo));
    return new MmdAmmoPhysics(scene);
  }

  async function load() {
    const runtime = new MmdRuntime(scene, await buildPhysics());
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

  // weights: {a, i, u, e, o}. No runtime animation is set, so nothing
  // overwrites the morph weights between frames.
  function setMouth(weights) {
    if (!mmdModel) return;
    for (const [name, weight] of Object.entries(mmdMouthMorphs(weights))) {
      if (availableMorphs.has(name)) mmdModel.morph.setMorphWeight(name, weight);
    }
  }

  // No-op until expressions land (#24).
  function setExpression(_name, _weight) {}

  // No-op until idle / dance motions land (#22, #25).
  function playMotion(_name) {}

  return { load, setMouth, setExpression, playMotion };
}
