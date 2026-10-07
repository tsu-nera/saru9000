// Motion loading policy, kept free of Babylon imports so it can be tested.
// load(url) -> animation, apply(animation) -> void. Missing or broken motion
// files must never break the stage: every failure becomes one log line.
export function createMotionPlayer({ load, apply, log = console.log, files = { idle: "/idle.vmd" } }) {
  async function playMotion(name) {
    const url = files[name];
    if (!url) {
      log(`motion "${name}": unknown motion`);
      return;
    }
    try {
      apply(await load(url));
    } catch (error) {
      // The vite dev server answers missing files with index.html (200), so
      // the real loader fails at parse time; this catch covers that too.
      log(`motion "${name}": ${url} not available (${error?.message ?? String(error)})`);
    }
  }

  return { playMotion };
}
