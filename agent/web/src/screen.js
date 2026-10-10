// The log screen behind the avatar: a lit plane whose texture is a canvas of
// text. Redrawn only when a line came in while it is shown.
import { Color3, DynamicTexture, MeshBuilder, StandardMaterial } from "@babylonjs/core";
import { createLogLines, tail } from "./logLines.js";

const WIDTH = 36;
const HEIGHT = 20.25; // 16:9
const POSITION = [0, 11, 10]; // the camera sits at -z, so this is behind Miku
const TEXTURE_WIDTH = 1024;
const TEXTURE_HEIGHT = 576;

const BACKGROUND = "#030a0a";
const FONT_SIZE = 20;
const FONT = `${FONT_SIZE}px ui-monospace, monospace`;
const LINE_HEIGHT = 24;
const MARGIN = 16;

// Miku's #39C5BB, brighter for what is being said.
const COLORS = {
  claude: "#b4fff8",
  user: "#7fe8de",
  speech: "#39C5BB",
  tool: "#39C5BB",
  claude_in: "#39C5BB",
  done: "#39C5BB",
  system: "#1f6e68",
};

export function createScreen(scene, { enabled = true } = {}) {
  const lines = createLogLines();
  const mesh = MeshBuilder.CreatePlane("screen", { width: WIDTH, height: HEIGHT }, scene);
  mesh.position.set(...POSITION);
  mesh.isPickable = false;
  mesh.setEnabled(enabled);

  const texture = new DynamicTexture("screenTexture", { width: TEXTURE_WIDTH, height: TEXTURE_HEIGHT }, scene, false);
  const material = new StandardMaterial("screenMaterial", scene);
  material.diffuseColor = Color3.Black();
  material.emissiveTexture = texture;
  material.disableLighting = true;
  mesh.material = material;

  const context = texture.getContext();
  let dirty = true;

  function draw() {
    context.fillStyle = BACKGROUND;
    context.fillRect(0, 0, TEXTURE_WIDTH, TEXTURE_HEIGHT);
    context.font = FONT;
    context.textBaseline = "top";
    const columns = Math.floor((TEXTURE_WIDTH - MARGIN * 2) / context.measureText("M").width);
    const rows = Math.floor((TEXTURE_HEIGHT - MARGIN * 2) / LINE_HEIGHT);
    tail(lines.lines(), columns, rows).forEach(({ kind, text }, i) => {
      context.fillStyle = COLORS[kind] ?? COLORS.system;
      context.fillText(text, MARGIN, MARGIN + i * LINE_HEIGHT);
    });
    texture.update();
  }

  scene.onBeforeRenderObservable.add(() => {
    if (!dirty || !mesh.isEnabled()) return;
    dirty = false;
    draw();
  });

  return {
    mesh,
    add(msg) {
      lines.add(msg);
      dirty = true;
    },
    setEnabled(on) {
      mesh.setEnabled(on);
      if (on) dirty = true;
    },
    toggle() {
      this.setEnabled(!mesh.isEnabled());
    },
  };
}
