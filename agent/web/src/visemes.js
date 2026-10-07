// Pure viseme helpers: no DOM, no Babylon.
export const VOWELS = ["a", "i", "u", "e", "o"];

// visemes: [{t, v}] sorted by segment start time (seconds from wav start).
export function targetVowel(visemes, t) {
  let vowel = "closed";
  for (const entry of visemes) {
    if (entry.t > t) break;
    vowel = entry.v;
  }
  return vowel;
}

export function targetWeights(vowel) {
  return Object.fromEntries(VOWELS.map((v) => [v, v === vowel ? 1 : 0]));
}

// Move each weight linearly toward target; 0 -> 1 takes rampSeconds.
export function approach(current, target, dt, rampSeconds = 0.05) {
  const step = dt / rampSeconds;
  const next = {};
  for (const v of VOWELS) {
    const from = current[v] ?? 0;
    const delta = (target[v] ?? 0) - from;
    next[v] = Math.abs(delta) <= step ? from + delta : from + Math.sign(delta) * step;
  }
  return next;
}
