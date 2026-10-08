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
        await ws.send_json({"type": "listen_mode", "mode": "wake"})
        async for msg in ws:
            received.append(msg.json())
            if msg.json()["type"] == "listen_mode":
                await ws.send_json(msg.json())
                continue
            await ws.send_json({"type": "state", "state": "thinking"})
            await ws.send_json({"type": "state", "state": "speaking"})
            for text in replies:
                await ws.send_json({"type": "utterance", "who": "agent", "name": "サル", "text": text})
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
    assert keyboard.screens[1] == "[mode: wake]\nyou> サル> やあ。元気だよ！\n"


def test_mode_line_sends_listen_mode_and_shows_the_core_confirmation():
    received = []
    out = io.StringIO()
    keyboard = Keyboard(["/mode always", "/mode wake", "こんにちは"], out)

    async def run():
        async with TestServer(fake_core(received, ["やあ。"])) as server:
            return await client.chat(str(server.make_url("")), read_line=keyboard, out=out)

    assert asyncio.run(run()) is True
    assert received == [
        {"type": "listen_mode", "mode": "always"},
        {"type": "listen_mode", "mode": "wake"},
        {"type": "text_input", "text": "こんにちは"},
    ]
    # The core's reply is printed before the next prompt, and a text_input still gets its label.
    assert keyboard.screens[1].endswith("[mode: always]\n")
    assert keyboard.screens[2].endswith("[mode: wake]\n")
    assert out.getvalue().endswith("you> サル> やあ。\nyou> \n")


def test_bad_mode_prints_usage_and_sends_nothing():
    received = []
    out = io.StringIO()
    keyboard = Keyboard(["/mode", "/mode xxx", "/mode wake now"], out)

    async def run():
        async with TestServer(fake_core(received, [])) as server:
            return await client.chat(str(server.make_url("")), read_line=keyboard, out=out)

    assert asyncio.run(run()) is True
    assert received == []
    assert out.getvalue().count("usage: /mode wake|always\n") == 3


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
