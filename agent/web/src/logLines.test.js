import { describe, expect, it } from "vitest";
import { createLogLines, tail, wrap } from "./logLines.js";

describe("createLogLines", () => {
  it("adds lines in order", () => {
    const log = createLogLines();
    log.add({ kind: "system", text: "a" });
    log.add({ kind: "user", text: "b" });
    expect(log.lines()).toEqual([
      { kind: "system", text: "a" },
      { kind: "user", text: "b" },
    ]);
  });

  it("appends to the last line of the same kind", () => {
    const log = createLogLines();
    log.add({ kind: "claude", text: "こん", append: true });
    log.add({ kind: "claude", text: "にちは", append: true });
    expect(log.lines()).toEqual([{ kind: "claude", text: "こんにちは" }]);
  });

  it("starts a new line when appending after another kind", () => {
    const log = createLogLines();
    log.add({ kind: "claude", text: "a", append: true });
    log.add({ kind: "tool", text: "t" });
    log.add({ kind: "claude", text: "b", append: true });
    expect(log.lines().map((l) => l.text)).toEqual(["a", "t", "b"]);
  });

  it("does not append without the flag", () => {
    const log = createLogLines();
    log.add({ kind: "claude", text: "a" });
    log.add({ kind: "claude", text: "b" });
    expect(log.lines()).toHaveLength(2);
  });

  it("splits text at newlines; only the first part may append", () => {
    const log = createLogLines();
    log.add({ kind: "claude", text: "a", append: true });
    log.add({ kind: "claude", text: "b\nc\nd", append: true });
    expect(log.lines().map((l) => l.text)).toEqual(["ab", "c", "d"]);
  });

  it("drops the oldest lines past maxLines", () => {
    const log = createLogLines({ maxLines: 3 });
    for (const text of ["1", "2", "3", "4", "5"]) log.add({ kind: "system", text });
    expect(log.lines().map((l) => l.text)).toEqual(["3", "4", "5"]);
  });
});

describe("wrap", () => {
  it("cuts ASCII at the column count", () => {
    expect(wrap("abcdefg", 3)).toEqual(["abc", "def", "g"]);
  });
  it("counts full-width characters as two columns", () => {
    expect(wrap("あいうえお", 6)).toEqual(["あいう", "えお"]);
    expect(wrap("aあいb", 4)).toEqual(["aあ", "いb"]);
  });
  it("gives one empty row for an empty text", () => {
    expect(wrap("", 10)).toEqual([""]);
  });
  it("keeps a character wider than the screen on its own row", () => {
    expect(wrap("あい", 1)).toEqual(["あ", "い"]);
  });
});

describe("tail", () => {
  it("returns the last rows after wrapping, keeping kinds", () => {
    const lines = [
      { kind: "user", text: "abcd" },
      { kind: "claude", text: "xy" },
    ];
    expect(tail(lines, 2, 2)).toEqual([
      { kind: "user", text: "cd" },
      { kind: "claude", text: "xy" },
    ]);
    expect(tail(lines, 2, 10)).toHaveLength(3);
  });
});
