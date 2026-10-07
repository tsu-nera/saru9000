import { describe, expect, it } from "vitest";
import {
  EXPRESSION_FADE_SECONDS,
  approachMorphs,
  eyesClosed,
  mmdExpressionMorphs,
  mmdMouthMorphs,
} from "./mmdMorphs.js";

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

describe("mmdExpressionMorphs", () => {
  const zeros = { 笑い: 0, にこり: 0, 困る: 0, 怒り: 0, 上: 0 };
  it.each([
    ["happy", { 笑い: 1, にこり: 1 }],
    ["sad", { 困る: 1 }],
    ["angry", { 怒り: 1 }],
    ["surprised", { 上: 1 }],
    ["relaxed", { にこり: 0.6 }],
  ])("%s follows the table and clears the rest", (name, weights) => {
    expect(mmdExpressionMorphs(name)).toEqual({ ...zeros, ...weights });
  });
  it("neutral -> every expression morph 0", () => {
    expect(mmdExpressionMorphs("neutral")).toEqual(zeros);
  });
  it("never touches mouth morphs", () => {
    const names = Object.keys(mmdExpressionMorphs("happy"));
    for (const mouth of ["あ", "い", "う", "え", "お"]) expect(names).not.toContain(mouth);
  });
  it("scales by weight", () => {
    expect(mmdExpressionMorphs("relaxed", 0.5).にこり).toBeCloseTo(0.3);
  });
  it("unknown name -> null", () => {
    expect(mmdExpressionMorphs("sleepy")).toBeNull();
  });
});

describe("approachMorphs", () => {
  it("reaches the target in about 0.2 s", () => {
    const target = mmdExpressionMorphs("happy");
    let face = mmdExpressionMorphs("neutral");
    face = approachMorphs(face, target, EXPRESSION_FADE_SECONDS / 2);
    expect(face.笑い).toBeCloseTo(0.5);
    face = approachMorphs(face, target, EXPRESSION_FADE_SECONDS / 2);
    expect(face).toEqual(target);
  });
  it("fades back to neutral", () => {
    const face = approachMorphs(mmdExpressionMorphs("happy"), mmdExpressionMorphs("neutral"), 1);
    expect(Object.values(face).every((w) => w === 0)).toBe(true);
  });
});

describe("eyesClosed", () => {
  it("is true for faces with 笑い or はぅ only", () => {
    expect(eyesClosed(mmdExpressionMorphs("happy"))).toBe(true);
    expect(eyesClosed({ はぅ: 0.4 })).toBe(true);
    expect(eyesClosed(mmdExpressionMorphs("relaxed"))).toBe(false);
    expect(eyesClosed(mmdExpressionMorphs("neutral"))).toBe(false);
  });
});
