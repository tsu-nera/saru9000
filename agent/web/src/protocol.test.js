import { beforeEach, describe, expect, it, vi } from "vitest";
import { createProtocol } from "./protocol.js";

class FakeWebSocket {
  static instances = [];
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    FakeWebSocket.instances.push(this);
  }
  send(data) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.readyState = 3;
  }
  // test helpers
  open() {
    this.readyState = 1;
    this.onopen();
  }
  receive(data) {
    this.onmessage({ data: typeof data === "string" ? data : JSON.stringify(data) });
  }
  drop() {
    this.readyState = 3;
    this.onclose();
  }
}

function setup() {
  const handlers = { speak: vi.fn(), state: vi.fn(), utterance: vi.fn(), expression: vi.fn(), motion: vi.fn() };
  const timers = [];
  const protocol = createProtocol({
    url: "ws://test/ws?role=stage",
    WebSocketImpl: FakeWebSocket,
    handlers,
    setTimeoutImpl: (fn, ms) => timers.push({ fn, ms }) - 1,
    clearTimeoutImpl: vi.fn(),
  });
  return { protocol, handlers, timers, ws: () => FakeWebSocket.instances.at(-1) };
}

beforeEach(() => {
  FakeWebSocket.instances = [];
});

describe("protocol", () => {
  it("sends ready on open", () => {
    const { ws } = setup();
    ws().open();
    expect(ws().sent).toEqual([{ type: "ready", avatar: "mmd" }]);
  });

  it("dispatches speak, state, utterance, expression, motion", () => {
    const { ws, handlers } = setup();
    ws().open();
    const speak = { type: "speak", id: 1, text: "hi", wav: "", visemes: [] };
    ws().receive(speak);
    ws().receive({ type: "state", state: "speaking" });
    ws().receive({ type: "utterance", who: "agent", name: "サル", text: "hi" });
    ws().receive({ type: "expression", name: "happy" });
    ws().receive({ type: "motion", name: "dance" });
    expect(handlers.speak).toHaveBeenCalledWith(speak);
    expect(handlers.state).toHaveBeenCalledWith({ type: "state", state: "speaking" });
    expect(handlers.utterance).toHaveBeenCalledWith({ type: "utterance", who: "agent", name: "サル", text: "hi" });
    expect(handlers.expression).toHaveBeenCalledTimes(1);
    expect(handlers.motion).toHaveBeenCalledTimes(1);
  });

  it("ignores unknown types and invalid JSON", () => {
    const { ws, handlers } = setup();
    ws().open();
    expect(() => {
      ws().receive({ type: "bogus" });
      ws().receive("not json {");
      ws().receive("null");
    }).not.toThrow();
    for (const h of Object.values(handlers)) expect(h).not.toHaveBeenCalled();
  });

  it("send drops silently when not open", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { protocol, ws } = setup();
    protocol.send({ type: "text_input", text: "x" });
    expect(ws().sent).toEqual([]);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it("reconnects with doubling delay capped at 10s, resetting on open", () => {
    const { ws, timers } = setup();
    const delays = [];
    for (let k = 0; k < 7; k++) {
      ws().drop();
      delays.push(timers.at(-1).ms);
      timers.at(-1).fn();
    }
    expect(delays).toEqual([500, 1000, 2000, 4000, 8000, 10000, 10000]);
    expect(FakeWebSocket.instances).toHaveLength(8);

    ws().open();
    ws().drop();
    expect(timers.at(-1).ms).toBe(500);
  });

  it("close stops reconnecting", () => {
    const { protocol, ws, timers } = setup();
    protocol.close();
    ws()?.onclose?.();
    expect(timers).toHaveLength(0);
  });
});
