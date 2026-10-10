// WebSocket link to core (/ws?role=stage). Dispatches messages by type
// and reconnects with exponential backoff.
const INITIAL_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 10000;
const DISPATCH = ["speak", "state", "utterance", "expression", "motion", "stop_motion", "listen_mode", "log"];

export function createProtocol({
  url,
  WebSocketImpl = globalThis.WebSocket,
  handlers,
  setTimeoutImpl = setTimeout,
  clearTimeoutImpl = clearTimeout,
}) {
  let ws = null;
  let backoff = INITIAL_BACKOFF_MS;
  let timer = null;
  let closed = false;

  function connect() {
    timer = null;
    ws = new WebSocketImpl(url);
    ws.onopen = () => {
      backoff = INITIAL_BACKOFF_MS;
      send({ type: "ready", avatar: "mmd" });
    };
    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      if (!msg || !DISPATCH.includes(msg.type)) {
        console.debug("protocol: ignoring message", msg?.type);
        return;
      }
      handlers[msg.type]?.(msg);
    };
    ws.onclose = () => {
      ws = null;
      if (closed) return;
      timer = setTimeoutImpl(connect, backoff);
      backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
    };
  }

  function send(obj) {
    if (!ws || ws.readyState !== 1) {
      console.warn("protocol: not connected, dropping", obj?.type);
      return;
    }
    ws.send(JSON.stringify(obj));
  }

  function close() {
    closed = true;
    if (timer !== null) clearTimeoutImpl(timer);
    timer = null;
    ws?.close();
  }

  connect();
  return { send, close };
}
