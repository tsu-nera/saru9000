// Abstract mouth weights -> MMD morph weights. Pure, so it is testable
// without loading Babylon. Miku has no え morph: it is approximated by
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
