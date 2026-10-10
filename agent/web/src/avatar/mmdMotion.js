// Motion loading policy, kept free of Babylon imports so it can be tested.
// load(name, motion) -> loaded, apply(name, loaded) -> void, or for a one-shot
// motion a promise that settles when it has finished. Missing or broken motion
// files must never break the stage: every failure becomes one log line, and a
// one-shot motion always ends with ended(name) so core is never left waiting.
export const MOTIONS = {
  idle: { url: "/idle.vmd", loop: true },
  // Dances: the first of `music` that the server has is played in sync with the VMD.
  // core sends these names (agent/core/config.json "dances"). No .m4a: core serves it
  // as application/octet-stream, which findAudio does not take for audio.
  mikumiku: { url: "/mikumiku.vmd", music: ["/mikumiku.mp3", "/mikumiku.wav"] },
  tellyourworld: { url: "/tellyourworld.vmd", music: ["/tellyourworld.mp3", "/tellyourworld.wav"] },
};

export function createMotionPlayer({ load, apply, ended = () => {}, log = console.log, motions = MOTIONS }) {
  async function playMotion(name) {
    const motion = motions[name];
    if (!motion) {
      log(`motion "${name}": unknown motion`);
      ended(name);
      return;
    }
    try {
      const finished = apply(name, await load(name, motion));
      if (!motion.loop) await finished;
    } catch (error) {
      // The vite dev server answers missing files with index.html (200), so
      // the real loader fails at parse time; this catch covers that too.
      log(`motion "${name}": ${motion.url} not available (${error?.message ?? String(error)})`);
    }
    if (!motion.loop) ended(name);
  }

  return { playMotion };
}

// The first url the server really has as audio. Checks the content type
// because the vite dev server answers missing files with index.html.
export async function findAudio(urls, fetchImpl = globalThis.fetch) {
  for (const url of urls) {
    try {
      const response = await fetchImpl(url, { method: "HEAD" });
      if (response.ok && (response.headers.get("content-type") ?? "").startsWith("audio/")) return url;
    } catch {
      // try the next one
    }
  }
  throw new Error(`no music (${urls.join(", ")})`);
}
