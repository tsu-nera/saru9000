// Abstract mouth and expression weights -> MMD morph weights. Pure, so it is
// testable without loading Babylon. Miku has no え morph: it is approximated by
// half あ + half い.
const clamp01 = (x) => Math.min(1, Math.max(0, x));

export function mmdMouthMorphs({ a = 0, i = 0, u = 0, e = 0, o = 0 }) {
  return {
    あ: clamp01(a + 0.5 * e),
    い: clamp01(i + 0.5 * e),
    う: clamp01(u),
    お: clamp01(o),
  };
}

// Expression name -> morph weights at full strength. Mouth morphs are left out:
// they would fight the lip sync.
export const EXPRESSIONS = {
  happy: { 笑い: 1, にこり: 1 },
  sad: { 困る: 1 },
  angry: { 怒り: 1 },
  surprised: { 上: 1 },
  relaxed: { にこり: 0.6 },
  neutral: {},
};

export const EXPRESSION_MORPHS = [...new Set(Object.values(EXPRESSIONS).flatMap(Object.keys))];

// Morphs that close the eyes; blinking on top of them looks broken.
export const EYES_CLOSED_MORPHS = ["笑い", "はぅ"];

// Every expression morph, so switching faces also clears the previous one.
// null for an unknown name.
export function mmdExpressionMorphs(name, weight = 1) {
  const table = EXPRESSIONS[name];
  if (!table) return null;
  return Object.fromEntries(EXPRESSION_MORPHS.map((m) => [m, clamp01((table[m] ?? 0) * weight)]));
}

export const EXPRESSION_FADE_SECONDS = 0.2;

// Move each morph linearly toward target; a full 0 -> 1 takes `seconds`.
export function approachMorphs(current, target, dt, seconds = EXPRESSION_FADE_SECONDS) {
  const step = dt / seconds;
  const next = {};
  for (const [name, to] of Object.entries(target)) {
    const from = current[name] ?? 0;
    const delta = to - from;
    next[name] = Math.abs(delta) <= step ? to : from + Math.sign(delta) * step;
  }
  return next;
}

export function eyesClosed(morphs) {
  return EYES_CLOSED_MORPHS.some((m) => (morphs[m] ?? 0) > 0);
}
