import { describe, expect, it, vi } from "vitest";
import { createMotionPlayer } from "./mmdMotion.js";

describe("createMotionPlayer", () => {
  it("does not throw when the file is missing; logs one line", async () => {
    const log = vi.fn();
    const apply = vi.fn();
    const load = vi.fn().mockRejectedValue(new Error("404"));
    const player = createMotionPlayer({ load, apply, log });
    await expect(player.playMotion("idle")).resolves.toBeUndefined();
    expect(load).toHaveBeenCalledWith("/idle.vmd");
    expect(apply).not.toHaveBeenCalled();
    expect(log).toHaveBeenCalledTimes(1);
  });

  it("applies the loaded animation", async () => {
    const animation = { endFrame: 100 };
    const apply = vi.fn();
    const log = vi.fn();
    const player = createMotionPlayer({ load: async () => animation, apply, log });
    await player.playMotion("idle");
    expect(apply).toHaveBeenCalledWith(animation);
    expect(log).not.toHaveBeenCalled();
  });

  it("logs once and returns for an unknown name", async () => {
    const load = vi.fn();
    const log = vi.fn();
    await createMotionPlayer({ load, apply: vi.fn(), log }).playMotion("nope");
    expect(load).not.toHaveBeenCalled();
    expect(log).toHaveBeenCalledTimes(1);
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
});
