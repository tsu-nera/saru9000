#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["claude-agent-sdk", "aiohttp", "sherpa-onnx>=1.13.8", "numpy"]
# ///
"""saru-core: the resident server behind the stage and text clients.

Serves /ws (JSON messages, spec in issue #18) and, when agent/web/dist exists,
the stage's static files. See README.md.

    ./server.py
    ./server.py --model opus --port 8765
    ./server.py --listen                         # hear the user through the mic
    ./server.py --audio-in a.wav --audio-in b.wav  # hear wav files instead
"""

import argparse
import asyncio
import logging
from pathlib import Path

from aiohttp import WSMsgType, web

import brain
import config
import listen
import protocol
import session
import speech
import tools

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


async def hear(sess, mic, audio_in):
    """Feed the session from the mic or wav files; a failure stops hearing, not the server."""
    try:
        listener = await asyncio.to_thread(listen.open_listener)
        if audio_in:
            # Played before a stage is open, the replies would be text only.
            log.info("--audio-in waits for a stage to connect")
            await sess.stage_ready.wait()
            await sess.listen(listener, listen.wav_blocks(audio_in), one_at_a_time=True)
            log.info("finished --audio-in, no longer listening")
        elif mic:
            await sess.listen(listener, listen.microphone())
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("listening failed, text input only from now on")


def make_app(model, mic=False, audio_in=None):
    app = web.Application()
    # Read before serving, so a bad config stops the server at startup.
    settings = config.load_config()
    character = config.load_character(settings)

    async def brain_ctx(app):
        log.info("character: %s (voice %s)", character.name, character.voice)
        voicevox = speech.Voicevox(settings["voicevox_url"], character.voice)
        # The tools' handlers live on the session, so it comes before the brain.
        app["session"] = sess = session.Session(None, voicevox, name=character.name)
        async with brain.ClaudeBrain(character.persona, model, tools.registry(dance=sess.dance)) as claude:
            sess.brain = claude
            hearing = None
            if mic or audio_in:
                hearing = asyncio.create_task(hear(sess, mic, audio_in))
            yield
            if hearing is not None:
                hearing.cancel()
                await asyncio.gather(hearing, return_exceptions=True)
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
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument("--listen", action="store_true", help="hear the user through the mic with ReazonSpeech")
    sources.add_argument(
        "--audio-in",
        action="append",
        metavar="WAV",
        help="hear 16 kHz mono 16-bit wav files instead of the mic; the server keeps running after them",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    brain.drop_api_key()
    web.run_app(make_app(args.model, args.listen, args.audio_in), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
