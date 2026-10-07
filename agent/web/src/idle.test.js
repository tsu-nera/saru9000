import { describe, expect, it } from "vitest";
import {
  BLINK_CLOSE,
  BLINK_OPEN,
  BLINK_MAX_INTERVAL,
  BLINK_MIN_INTERVAL,
  blinkWeight,
  createBlinker,
} from "./idle.js";

const DT = 1 / 120;

describe("blinkWeight", () => {
  it("ramps 0 -> 1 -> 0 and is 0 outside the blink", () => {
    expect(blinkWeight(-1)).toBe(0);
    expect(blinkWeight(0)).toBe(0);
    expect(blinkWeight(BLINK_CLOSE / 2)).toBeCloseTo(0.5);
    expect(blinkWeight(BLINK_CLOSE)).toBeCloseTo(1);
    expect(blinkWeight(BLINK_CLOSE + BLINK_OPEN / 2)).toBeCloseTo(0.5);
    expect(blinkWeight(BLINK_CLOSE + BLINK_OPEN)).toBe(0);
    expect(blinkWeight(10)).toBe(0);
  });
});

describe("createBlinker", () => {
  function run(randoms, seconds) {
    let i = 0;
    const random = () => randoms[i++ % randoms.length];
    const samples = [];
    let t = 0;
    const blinker = createBlinker({ setBlink: (w) => samples.push({ t, w }), random });
    while (t < seconds) {
      t += DT;
      blinker.update(DT);
    }
    return samples;
  }

  // Times where the weight leaves 0.
  function starts(samples) {
    const out = [];
    let prev = 0;
    for (const { t, w } of samples) {
      if (prev === 0 && w > 0) out.push(t - DT);
      prev = w;
    }
    return out;
  }

  const randoms = [0, 0.5, 1, 0.25];
  const samples = run(randoms, 30);
  const begin = starts(samples);

  it("starts blinks 2-6 s apart following the random source", () => {
    expect(begin.length).toBeGreaterThanOrEqual(5);
    expect(Math.abs(begin[0] - (BLINK_MIN_INTERVAL + 4 * randoms[0]))).toBeLessThan(2 * DT);
    for (let k = 1; k < begin.length; k++) {
      const gap = begin[k] - begin[k - 1];
      expect(gap).toBeGreaterThanOrEqual(BLINK_MIN_INTERVAL - 2 * DT);
      expect(gap).toBeLessThanOrEqual(BLINK_MAX_INTERVAL + 2 * DT);
      expect(Math.abs(gap - (2 + 4 * randoms[k % randoms.length]))).toBeLessThan(2 * DT);
    }
  });

  it("weight goes 0 -> 1 -> 0 on schedule", () => {
    const at = (time) => samples.reduce((a, b) => (Math.abs(b.t - time) < Math.abs(a.t - time) ? b : a)).w;
    for (const start of begin.slice(0, 4)) {
      expect(at(start - 2 * DT)).toBe(0);
      // start is detected to within one frame, which is ~14% of the close ramp
      expect(at(start + BLINK_CLOSE)).toBeGreaterThan(0.8);
      expect(at(start + BLINK_CLOSE + BLINK_OPEN + 2 * DT)).toBe(0);

      const inBlink = samples.filter((s) => s.t > start && s.t < start + BLINK_CLOSE + BLINK_OPEN);
      const max = Math.max(...inBlink.map((s) => s.w));
      expect(max).toBeGreaterThan(0.95);
      const peak = inBlink.findIndex((s) => s.w === max);
      for (let k = 1; k <= peak; k++) expect(inBlink[k].w).toBeGreaterThanOrEqual(inBlink[k - 1].w);
      for (let k = peak + 1; k < inBlink.length; k++) expect(inBlink[k].w).toBeLessThanOrEqual(inBlink[k - 1].w);
    }
  });
});
