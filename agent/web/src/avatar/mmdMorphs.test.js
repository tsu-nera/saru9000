import { describe, expect, it } from "vitest";
import { mmdMouthMorphs } from "./mmdMorphs.js";

describe("mmdMouthMorphs", () => {
  it("e -> あ 0.5 + い 0.5", () => {
    expect(mmdMouthMorphs({ a: 0, i: 0, u: 0, e: 1, o: 0 })).toEqual({ あ: 0.5, い: 0.5, う: 0, お: 0 });
  });
  it("a -> あ 1", () => {
    expect(mmdMouthMorphs({ a: 1, i: 0, u: 0, e: 0, o: 0 })).toEqual({ あ: 1, い: 0, う: 0, お: 0 });
  });
  it("i, u, o map to their own morph", () => {
    expect(mmdMouthMorphs({ i: 1 }).い).toBe(1);
    expect(mmdMouthMorphs({ u: 1 }).う).toBe(1);
    expect(mmdMouthMorphs({ o: 1 }).お).toBe(1);
  });
  it("closed -> all mouth morphs 0", () => {
    const morphs = mmdMouthMorphs({ a: 0, i: 0, u: 0, e: 0, o: 0 });
    expect(Object.values(morphs).every((w) => w === 0)).toBe(true);
  });
  it("clamps to [0, 1]", () => {
    expect(mmdMouthMorphs({ a: 1, e: 1 }).あ).toBe(1);
  });
});
