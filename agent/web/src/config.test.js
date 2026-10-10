import { describe, expect, it } from "vitest";
import { cameraFromParams, loadConfig, mergeConfig, screenFromParams } from "./config.js";

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
  it("is empty without the parameter, so the file value stays", () => {
    expect(screenFromParams(new URLSearchParams("distance=18"))).toEqual({});
  });
  it("reads 0 as off and anything else as on", () => {
    expect(screenFromParams(new URLSearchParams("screen=0"))).toEqual({ enabled: false });
    expect(screenFromParams(new URLSearchParams("screen=1"))).toEqual({ enabled: true });
  });
});

describe("loadConfig", () => {
  it("applies stage.local.json over stage.json, then URL parameters", async () => {
    const config = await loadConfig(
      fakeFetch({ "/stage.json": defaults, "/stage.local.json": { camera: { height: 12, distance: 22 } } }),
      new URLSearchParams("distance=30"),
    );
    expect(config.camera).toEqual({ distance: 30, height: 12, elevation: 6.3 });
  });
  it("works without stage.local.json", async () => {
    const config = await loadConfig(fakeFetch({ "/stage.json": defaults }), new URLSearchParams());
    expect(config).toEqual({ ...defaults, screen: {} });
  });
  it("lets ?screen= override screen.enabled in stage.json", async () => {
    const on = { ...defaults, screen: { enabled: true } };
    const off = { ...defaults, screen: { enabled: false } };
    const enabled = async (file, query) =>
      (await loadConfig(fakeFetch({ "/stage.json": file }), new URLSearchParams(query))).screen.enabled;
    expect(await enabled(on, "screen=0")).toBe(false);
    expect(await enabled(off, "screen=1")).toBe(true);
    expect(await enabled(on, "")).toBe(true);
  });
  it("fails when stage.json is missing", async () => {
    await expect(loadConfig(fakeFetch({}), new URLSearchParams())).rejects.toThrow("/stage.json is missing");
  });
});
