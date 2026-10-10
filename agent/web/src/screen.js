// The VJ-style screen behind the avatar: a plane whose DynamicTexture shows
// core's log. The texture is redrawn only when a line arrived while visible.
import { Color3, DynamicTexture, MeshBuilder, StandardMaterial } from "@babylonjs/core";
import { createLogLines } from "./logLines.js";

// White, brightest for the conversation and dimmer (alpha over the dark
// background) for the machinery.
const COLORS = {
  claude: "rgb(255, 255, 255)",
  user: "rgba(255, 255, 255, 0.92)",
  tool: "rgba(255, 255, 255, 0.8)",
  claude_in: "rgba(255, 255, 255, 0.8)",
  done: "rgba(255, 255, 255, 0.8)",
  speech: "rgba(255, 255, 255, 0.7)",
  system: "rgba(255, 255, 255, 0.6)",
};

const TEXTURE_WIDTH = 1600;
const TEXTURE_HEIGHT = 900;
const FONT_PX = 26;
const LINE_PX = 32;
const MARGIN_PX = 24;
const COLUMNS = Math.floor((TEXTURE_WIDTH - MARGIN_PX * 2) / (FONT_PX * 0.6));
const MAX_LINES = Math.floor((TEXTURE_HEIGHT - MARGIN_PX * 2) / LINE_PX);

export function createScreen(scene, { position = { x: 0, y: 10, z: 8 }, width = 26 } = {}) {
  const buffer = createLogLines({ maxLines: MAX_LINES, columns: COLUMNS });
  const texture = new DynamicTexture("screen", { width: TEXTURE_WIDTH, height: TEXTURE_HEIGHT }, scene, false);
  const context = texture.getContext();

  const material = new StandardMaterial("screen", scene);
  // Unlit: with lighting off the diffuse texture shows as is. An emissiveTexture
  // is added on top of the white emissiveColor, which made the whole plane white.
  material.disableLighting = true;
  material.emissiveColor = Color3.White();
  material.diffuseTexture = texture;
  material.specularColor = Color3.Black();
  material.backFaceCulling = true;

  // The camera sits on -z, so the plane's front (-z side) faces it by default.
  const plane = MeshBuilder.CreatePlane("screen", { width, height: (width * 9) / 16 }, scene);
  plane.position.set(position.x, position.y, position.z);
  plane.material = material;
  plane.isPickable = false;

  let visible = true;
  let dirty = true;

  function draw() {
    dirty = false;
    context.fillStyle = "rgb(2, 14, 16)";
    context.fillRect(0, 0, TEXTURE_WIDTH, TEXTURE_HEIGHT);
    context.font = `bold ${FONT_PX}px monospace`;
    context.textBaseline = "top";
    let y = MARGIN_PX;
    for (const row of buffer.lines()) {
      context.fillStyle = COLORS[row.kind] ?? COLORS.system;
      context.fillText(row.text, MARGIN_PX, y);
      y += LINE_PX;
    }
    texture.update();
  }

  // Redraw lazily, at most once per frame, and never while hidden.
  scene.onBeforeRenderObservable.add(() => {
    if (visible && dirty) draw();
  });

  return {
    push(msg) {
      buffer.add(msg);
      dirty = true;
    },
    setVisible(value) {
      visible = value;
      plane.setEnabled(value);
    },
    toggle() {
      this.setVisible(!visible);
    },
    get visible() {
      return visible;
    },
  };
}
