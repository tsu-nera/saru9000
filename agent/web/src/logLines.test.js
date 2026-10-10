import { describe, expect, it } from "vitest";
import { createLogLines } from "./logLines.js";

const texts = (buffer) => buffer.lines().map((row) => row.text);

describe("createLogLines", () => {
  it("adds one line per entry with its kind", () => {
    const buffer = createLogLines();
    buffer.add({ kind: "user", text: "hello" });
    buffer.add({ kind: "system", text: "ready" });
    expect(buffer.lines()).toEqual([
      { kind: "user", text: "hello" },
      { kind: "system", text: "ready" },
    ]);
  });

  it("appends to the last line when the kind is the same", () => {
    const buffer = createLogLines();
    buffer.add({ kind: "claude", text: "He", append: true });
    buffer.add({ kind: "claude", text: "llo", append: true });
    expect(texts(buffer)).toEqual(["Hello"]);
  });

  it("starts a new line when appending onto a different kind", () => {
    const buffer = createLogLines();
    buffer.add({ kind: "claude", text: "Let me check", append: true });
    buffer.add({ kind: "tool", text: "weather {}" });
    buffer.add({ kind: "claude", text: "Sunny", append: true });
    expect(buffer.lines()).toEqual([
      { kind: "claude", text: "Let me check" },
      { kind: "tool", text: "weather {}" },
      { kind: "claude", text: "Sunny" },
    ]);
  });

  it("splits text with newlines into lines", () => {
    const buffer = createLogLines();
    buffer.add({ kind: "system", text: "a\nb" });
    expect(texts(buffer)).toEqual(["a", "b"]);
  });

  it("drops the oldest rows beyond maxLines", () => {
    const buffer = createLogLines({ maxLines: 3 });
    for (const n of [1, 2, 3, 4, 5]) buffer.add({ kind: "system", text: `line${n}` });
    expect(texts(buffer)).toEqual(["line3", "line4", "line5"]);
  });

  it("wraps long lines by columns and keeps only the last rows", () => {
    const buffer = createLogLines({ maxLines: 2, columns: 4 });
    buffer.add({ kind: "system", text: "abcdefghij" });
    expect(texts(buffer)).toEqual(["efgh", "ij"]);
  });

  it("counts full-width characters as two columns", () => {
    const buffer = createLogLines({ columns: 6 });
    buffer.add({ kind: "claude", text: "こんにちは" });
    expect(texts(buffer)).toEqual(["こんに", "ちは"]);
  });
});
