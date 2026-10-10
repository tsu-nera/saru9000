// The stage set (サイバーステージ, glb version) behind the avatar. The three glb
// files are loaded under one TransformNode, which carries the scale and the
// on/off. Their animations loop while the venue is shown.
import { LoadAssetContainerAsync, TransformNode } from "@babylonjs/core";
// Side-effect import registers the .glb scene loader plugin.
import "@babylonjs/loaders/glTF/glTFFileLoader.js";

const FILES = ["CyberStage_AB.glb", "CyberStage_C_Screen.glb", "CyberStage_D.glb"];

export function createVenue(scene, { scale, base = "/cyberstage/" }) {
  const root = new TransformNode("venue", scene);
  root.scaling.setAll(scale);

  const animationGroups = [];
  let visible = true;

  function applyPlayback() {
    for (const group of animationGroups) {
      if (visible) group.play(true);
      else group.pause();
    }
  }

  return {
    // Rejects when a file is missing or broken; the caller decides how loud to be.
    async load() {
      const containers = await Promise.all(FILES.map((file) => LoadAssetContainerAsync(base + file, scene)));
      for (const container of containers) {
        container.addAllToScene();
        // The glTF __root__ is the only node without a parent.
        for (const node of [...container.meshes, ...container.transformNodes]) {
          if (node.parent === null) node.parent = root;
        }
        for (const mesh of container.meshes) mesh.isPickable = false;
        animationGroups.push(...container.animationGroups);
      }
      applyPlayback();
    },
    setVisible(value) {
      visible = value;
      root.setEnabled(value);
      applyPlayback();
    },
    toggle() {
      this.setVisible(!visible);
    },
    get visible() {
      return visible;
    },
  };
}
