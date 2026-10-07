import { describe, expect, it } from "vitest";
import { approach, targetVowel, targetWeights } from "./visemes.js";

const timeline = [
  { t: 0.1, v: "a" },
  { t: 0.3, v: "i" },
  { t: 0.5, v: "closed" },
];

describe("targetVowel", () => {
  it("returns the entry starting exactly at t", () => {
    expect(targetVowel(timeline, 0.3)).toBe("i");
  });
  it("returns the previous entry just before a boundary", () => {
    expect(targetVowel(timeline, 0.2999)).toBe("a");
  });
  it("returns the covering entry between starts", () => {
    expect(targetVowel(timeline, 0.4)).toBe("i");
  });
  it("keeps the last entry after its start", () => {
    expect(targetVowel(timeline, 99)).toBe("closed");
    expect(targetVowel([{ t: 0, v: "u" }], 5)).toBe("u");
  });
  it("is closed before the first entry", () => {
    expect(targetVowel(timeline, 0.05)).toBe("closed");
    expect(targetVowel(timeline, -1)).toBe("closed");
  });
  it("is closed for an empty list", () => {
    expect(targetVowel([], 1)).toBe("closed");
  });
});

describe("targetWeights", () => {
  it("sets only the vowel to 1", () => {
    expect(targetWeights("e")).toEqual({ a: 0, i: 0, u: 0, e: 1, o: 0 });
  });
  it("closed -> all 0", () => {
    expect(targetWeights("closed")).toEqual({ a: 0, i: 0, u: 0, e: 0, o: 0 });
  });
  it("unknown -> all 0", () => {
    expect(targetWeights("zzz")).toEqual({ a: 0, i: 0, u: 0, e: 0, o: 0 });
  });
});

describe("approach", () => {
  const zero = targetWeights("closed");
  const a = targetWeights("a");

  it("reaches the target after 50ms", () => {
    let w = zero;
    for (let k = 0; k < 5; k++) w = approach(w, a, 0.01);
    expect(w.a).toBeCloseTo(1, 10);
    expect(w.i).toBe(0);
  });
  it("is halfway after 25ms", () => {
    let w = zero;
    w = approach(w, a, 0.025);
    expect(w.a).toBeCloseTo(0.5, 10);
  });
  it("never overshoots with a large dt", () => {
    const w = approach(zero, a, 10);
    expect(w.a).toBe(1);
    expect(approach(w, zero, 10).a).toBe(0);
  });
  it("moves toward closed (all 0) and does not mutate input", () => {
    const start = { a: 1, i: 0.4, u: 0, e: 0, o: 0 };
    const w = approach(start, zero, 0.05);
    expect(w).toEqual(zero);
    expect(start.a).toBe(1);
  });
});
