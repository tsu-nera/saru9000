import asyncio
import io
import os
import socket
import subprocess
import sys
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestServer

import client

CLIENT = Path(__file__).resolve().parent / "client.py"


def fake_core(received, replies):
    """A core that answers every text_input with the given utterances, then goes idle."""

    async def ws_handler(request):
        assert request.query["role"] == "viewer"
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json({"type": "state", "state": "idle"})
        async for msg in ws:
            received.append(msg.json())
            await ws.send_json({"type": "state", "state": "thinking"})
            await ws.send_json({"type": "state", "state": "speaking"})
            for text in replies:
                await ws.send_json({"type": "utterance", "who": "saru", "text": text})
            await ws.send_json({"type": "state", "state": "idle"})
        return ws

    app = web.Application()
    app.router.add_get("/ws", ws_handler)
    return app


class Keyboard:
    """Types the given lines, then Ctrl-D; remembers what was on screen at each prompt."""

    def __init__(self, lines, out):
        self.lines = list(lines)
        self.out = out
        self.screens = []

    def __call__(self, prompt):
        self.screens.append(self.out.getvalue())
        self.out.write(prompt)
        if not self.lines:
            raise EOFError
        return self.lines.pop(0)


def test_line_goes_as_text_input_and_replies_are_shown_before_the_next_prompt():
    received = []
    out = io.StringIO()
    keyboard = Keyboard(["こんにちは"], out)

    async def run():
        async with TestServer(fake_core(received, ["やあ。", "元気だよ！"])) as server:
            return await client.chat(str(server.make_url("")), read_line=keyboard, out=out)

    assert asyncio.run(run()) is True
    assert received == [{"type": "text_input", "text": "こんにちは"}]
    # The second prompt comes only after the turn is back to idle.
    assert len(keyboard.screens) == 2
    assert keyboard.screens[1] == "you> saru> やあ。元気だよ！\n"


def test_unreachable_core_ends_with_one_line_and_no_traceback():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    result = subprocess.run(
        [sys.executable, str(CLIENT)],
        env={**os.environ, "SARU_URL": url},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert result.stdout == f"cannot connect to saru-core at {url}\n"
    assert "Traceback" not in result.stderr
