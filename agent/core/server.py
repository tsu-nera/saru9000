#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["claude-agent-sdk", "aiohttp"]
# ///
"""saru-core: the resident server behind the stage and text clients.

Serves /ws (JSON messages, spec in issue #18) and, when agent/web/dist exists,
the stage's static files. See README.md.

    ./server.py
    ./server.py --model opus --port 8765
"""

import argparse
import logging
import os
from pathlib import Path

from aiohttp import WSMsgType, web

import brain
import protocol
import session
import speech

log = logging.getLogger("server")

DIST_DIR = Path(__file__).resolve().parents[1] / "web" / "dist"
ROLES = ("stage", "viewer")


class WsConnection:
    """What Session sees of a websocket: its role and a way to send."""

    def __init__(self, ws, role):
        self.ws = ws
        self.role = role

    async def send(self, message):
        await self.ws.send_json(message)


async def ws_handler(request):
    role = request.query.get("role", "viewer")
    if role not in ROLES:
        role = "viewer"
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    sess = request.app["session"]
    conn = WsConnection(ws, role)
    await sess.add(conn)
    log.info("connected: %s (%d total)", role, len(sess.connections))
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            message = protocol.parse(msg.data)
            if message is not None:
                await sess.handle(conn, message)
    finally:
        sess.remove(conn)
        log.info("disconnected: %s", role)
    return ws


async def index(request):
    return web.FileResponse(DIST_DIR / "index.html")


async def no_stage_files(request):
    return web.Response(
        status=404,
        text="agent/web/dist not found. Run `npm run build` in agent/web to serve the stage here.\n",
    )


def make_app(model):
    app = web.Application()

    async def brain_ctx(app):
        async with brain.ClaudeBrain(model) as claude:
            voicevox = speech.Voicevox(
                url=os.environ.get("VOICEVOX_URL", speech.DEFAULT_URL),
                speaker=int(os.environ.get("VOICEVOX_SPEAKER", speech.DEFAULT_SPEAKER)),
                speed=float(os.environ.get("VOICEVOX_SPEED", speech.DEFAULT_SPEED)),
            )
            app["session"] = sess = session.Session(claude, voicevox)
            yield
            await sess.close()

    app.cleanup_ctx.append(brain_ctx)
    app.router.add_get("/ws", ws_handler)
    if DIST_DIR.is_dir():
        app.router.add_get("/", index)
        app.router.add_static("/", DIST_DIR)
    else:
        app.router.add_get("/", no_stage_files)
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=brain.DEFAULT_MODEL)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    brain.drop_api_key()
    web.run_app(make_app(args.model), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
