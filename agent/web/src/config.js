// Stage settings: public/stage.json holds the defaults (committed),
// public/stage.local.json overrides them per machine (gitignored, optional),
// and URL parameters override both for trying values without editing files.

const DEFAULTS_URL = "/stage.json";
const LOCAL_URL = "/stage.local.json";

// URL parameter -> camera key. All are numbers.
const CAMERA_PARAMS = ["distance", "height", "elevation"];

export function cameraFromParams(params) {
  const camera = {};
  for (const key of CAMERA_PARAMS) {
    if (params.has(key)) camera[key] = Number(params.get(key));
  }
  return camera;
}

// ?screen=0|1 -> the log screen's on/off. null when the parameter is absent.
export function screenFromParams(params) {
  return params.has("screen") ? { enabled: params.get("screen") !== "0" } : null;
}

// ?venue=0|1 -> the stage set's on/off. null when the parameter is absent.
export function venueFromParams(params) {
  return params.has("venue") ? { enabled: params.get("venue") !== "0" } : null;
}

// Later layers win, key by key within each section.
export function mergeConfig(...layers) {
  const merged = {};
  for (const layer of layers) {
    for (const [section, values] of Object.entries(layer ?? {})) {
      if (values == null) continue;
      merged[section] = { ...merged[section], ...values };
    }
  }
  return merged;
}

// fetchJson(url) resolves to the parsed body, or null when the file is absent.
export async function loadConfig(fetchJson, params) {
  const defaults = await fetchJson(DEFAULTS_URL);
  if (!defaults) throw new Error(`${DEFAULTS_URL} is missing`);
  const local = await fetchJson(LOCAL_URL);
  return mergeConfig(defaults, local, {
    camera: cameraFromParams(params),
    screen: screenFromParams(params),
    venue: venueFromParams(params),
  });
}

export async function fetchJson(url) {
  const response = await fetch(url);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}
