import { describe, expect, it, vi } from "vitest";
import { MOTIONS, createMotionPlayer, findAudio } from "./mmdMotion.js";

describe("createMotionPlayer", () => {
  it("does not throw when the file is missing; logs one line", async () => {
    const log = vi.fn();
    const apply = vi.fn();
    const ended = vi.fn();
    const load = vi.fn().mockRejectedValue(new Error("404"));
    const player = createMotionPlayer({ load, apply, ended, log });
    await expect(player.playMotion("idle")).resolves.toBeUndefined();
    expect(load).toHaveBeenCalledWith("idle", MOTIONS.idle);
    expect(apply).not.toHaveBeenCalled();
    expect(log).toHaveBeenCalledTimes(1);
    // idle loops forever: it never reports an end.
    expect(ended).not.toHaveBeenCalled();
  });

  it("applies the loaded animation", async () => {
    const animation = { endFrame: 100 };
    const apply = vi.fn();
    const log = vi.fn();
    const player = createMotionPlayer({ load: async () => animation, apply, log });
    await player.playMotion("idle");
    expect(apply).toHaveBeenCalledWith("idle", animation);
    expect(log).not.toHaveBeenCalled();
  });

  it("logs once and ends an unknown name", async () => {
    const load = vi.fn();
    const log = vi.fn();
    const ended = vi.fn();
    await createMotionPlayer({ load, apply: vi.fn(), ended, log }).playMotion("nope");
    expect(load).not.toHaveBeenCalled();
    expect(log).toHaveBeenCalledTimes(1);
    expect(ended).toHaveBeenCalledWith("nope");
  });

  it("swallows errors thrown by apply", async () => {
    const log = vi.fn();
    const apply = () => {
      throw new Error("bad");
    };
    const player = createMotionPlayer({ load: async () => ({}), apply, log });
    await expect(player.playMotion("idle")).resolves.toBeUndefined();
    expect(log).toHaveBeenCalledTimes(1);
  });

  it("ends the dance at once when its files are missing", async () => {
    const log = vi.fn();
    const apply = vi.fn();
    const ended = vi.fn();
    const load = vi.fn().mockRejectedValue(new Error("no music"));
    await createMotionPlayer({ load, apply, ended, log }).playMotion("dance");
    expect(load).toHaveBeenCalledWith("dance", MOTIONS.dance);
    expect(apply).not.toHaveBeenCalled();
    expect(ended).toHaveBeenCalledTimes(1);
    expect(ended).toHaveBeenCalledWith("dance");
    expect(log).toHaveBeenCalledTimes(1);
  });

  it("ends the dance only after it has finished", async () => {
    let finish;
    const apply = vi.fn(() => new Promise((resolve) => (finish = resolve)));
    const ended = vi.fn();
    const playing = createMotionPlayer({ load: async () => ({}), apply, ended, log: vi.fn() }).playMotion("dance");
    await vi.waitFor(() => expect(apply).toHaveBeenCalled());
    expect(ended).not.toHaveBeenCalled();
    finish();
    await playing;
    expect(ended).toHaveBeenCalledWith("dance");
  });
});

describe("findAudio", () => {
  const response = (ok, type) => ({ ok, headers: { get: () => type } });

  it("returns the first url served as audio", async () => {
    const fetchImpl = vi.fn(async (url) =>
      url === "/a.mp3" ? response(true, "text/html") : response(true, "audio/wav"),
    );
    await expect(findAudio(["/a.mp3", "/a.wav"], fetchImpl)).resolves.toBe("/a.wav");
    expect(fetchImpl).toHaveBeenCalledWith("/a.mp3", { method: "HEAD" });
  });

  it("rejects when none is there", async () => {
    const fetchImpl = vi.fn(async () => response(false, null));
    await expect(findAudio(["/a.mp3"], fetchImpl)).rejects.toThrow("no music");
  });
});
