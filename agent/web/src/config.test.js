import { describe, expect, it } from "vitest";
import { cameraFromParams, loadConfig, mergeConfig, screenFromParams, venueFromParams } from "./config.js";

const defaults = { camera: { distance: 28, height: 10, elevation: 6.3 } };

function fakeFetch(files) {
  return async (url) => files[url] ?? null;
}

describe("mergeConfig", () => {
  it("lets later layers win key by key", () => {
    expect(mergeConfig(defaults, { camera: { distance: 20 } })).toEqual({
      camera: { distance: 20, height: 10, elevation: 6.3 },
    });
  });
  it("skips missing layers", () => {
    expect(mergeConfig(defaults, null, undefined)).toEqual(defaults);
  });
});

describe("cameraFromParams", () => {
  it("reads only the camera keys present, as numbers", () => {
    expect(cameraFromParams(new URLSearchParams("distance=18&autoplay=1"))).toEqual({ distance: 18 });
  });
});

describe("screenFromParams", () => {
  it("reads ?screen=0|1 and ignores a missing parameter", () => {
    expect(screenFromParams(new URLSearchParams("screen=0"))).toEqual({ enabled: false });
    expect(screenFromParams(new URLSearchParams("screen=1"))).toEqual({ enabled: true });
    expect(screenFromParams(new URLSearchParams())).toBeNull();
  });
});

describe("venueFromParams", () => {
  it("reads ?venue=0|1 and ignores a missing parameter", () => {
    expect(venueFromParams(new URLSearchParams("venue=0"))).toEqual({ enabled: false });
    expect(venueFromParams(new URLSearchParams("venue=1"))).toEqual({ enabled: true });
    expect(venueFromParams(new URLSearchParams())).toBeNull();
  });
});

describe("loadConfig", () => {
  it("lets ?venue=1 win over stage.json and keeps its scale", async () => {
    const config = await loadConfig(
      fakeFetch({ "/stage.json": { ...defaults, venue: { enabled: false, scale: 12.5 } } }),
      new URLSearchParams("venue=1"),
    );
    expect(config.venue).toEqual({ enabled: true, scale: 12.5 });
  });
  it("lets ?screen=0 win over stage.json", async () => {
    const config = await loadConfig(
      fakeFetch({ "/stage.json": { ...defaults, screen: { enabled: true } } }),
      new URLSearchParams("screen=0"),
    );
    expect(config.screen).toEqual({ enabled: false });
  });
  it("applies stage.local.json over stage.json, then URL parameters", async () => {
    const config = await loadConfig(
      fakeFetch({ "/stage.json": defaults, "/stage.local.json": { camera: { height: 12, distance: 22 } } }),
      new URLSearchParams("distance=30"),
    );
    expect(config.camera).toEqual({ distance: 30, height: 12, elevation: 6.3 });
  });
  it("works without stage.local.json", async () => {
    const config = await loadConfig(fakeFetch({ "/stage.json": defaults }), new URLSearchParams());
    expect(config).toEqual(defaults);
  });
  it("fails when stage.json is missing", async () => {
    await expect(loadConfig(fakeFetch({}), new URLSearchParams())).rejects.toThrow("/stage.json is missing");
  });
});
