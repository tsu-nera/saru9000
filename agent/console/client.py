#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["aiohttp"]
# ///
"""Text client of saru-core: type to saru and read its replies.

Connects to $SARU_URL/ws as a viewer. It knows nothing of Claude or VOICEVOX
and plays no sound (the stage does); it only sends text_input and prints the
core's utterances. See README.md.

    ./client.py
    SARU_URL=http://<vaio's tailnet address>:8765 ./client.py
"""

import asyncio
import os
import sys
import threading

import aiohttp

DEFAULT_URL = "http://127.0.0.1:8765"
# While the core is in these states it is answering and drops a text_input.
BUSY = ("thinking", "speaking")


class Follower:
    """Prints the agent's utterances and tells when the core is ready for the next input."""

    def __init__(self, out):
        self.out = out
        self.ready = asyncio.Event()
        self.closed = False
        self.labelled = False  # whether this reply's "<name>> " is printed yet

    async def follow(self, ws):
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self.receive(msg.json())
        finally:
            self.closed = True
            self.ready.set()

    def receive(self, message):
        if not isinstance(message, dict):
            return
        kind = message.get("type")
        if kind == "utterance" and message.get("who") == "agent":
            if not self.labelled:
                self.labelled = True
                self.out.write(f"{message.get('name', 'agent')}> ")
            self.out.write(str(message.get("text", "")))
            self.out.flush()
        elif kind == "state":
            if message.get("state") in BUSY:
                self.ready.clear()
            else:
                # The next reply, typed or heard, gets its own label.
                self.labelled = False
                self.ready.set()


def read_in_thread(read_line, prompt):
    """Run a blocking read_line in a daemon thread, so Ctrl-C need not wait for Enter."""
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def settle(result, error):
        if future.done():
            return
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(result)

    def run():
        try:
            line = read_line(prompt)
        except BaseException as e:  # EOFError (Ctrl-D) has to reach the loop too.
            loop.call_soon_threadsafe(settle, None, e)
        else:
            loop.call_soon_threadsafe(settle, line, None)

    threading.Thread(target=run, daemon=True).start()
    return future


async def chat(url, read_line=input, out=sys.stdout):
    """Talk until Ctrl-D; False if the core could not be reached or went away."""
    async with aiohttp.ClientSession() as http:
        try:
            ws = await http.ws_connect(f"{url.rstrip('/')}/ws?role=viewer")
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            out.write(f"cannot connect to saru-core at {url}\n")
            return False
        async with ws:
            follower = Follower(out)
            reader = asyncio.create_task(follower.follow(ws))
            try:
                while True:
                    # The core sends its state on connect, so this also waits for that.
                    await follower.ready.wait()
                    if follower.closed:
                        out.write(f"\nsaru-core at {url} closed the connection\n")
                        return False
                    try:
                        text = (await read_in_thread(read_line, "you> ")).strip()
                    except EOFError:
                        out.write("\n")
                        return True
                    if not text:
                        continue
                    follower.ready.clear()
                    await ws.send_json({"type": "text_input", "text": text})
                    await follower.ready.wait()
                    if not follower.closed:
                        out.write("\n")
            finally:
                reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)


def main():
    url = os.environ.get("SARU_URL", DEFAULT_URL)
    try:
        ok = asyncio.run(chat(url))
    except KeyboardInterrupt:
        print()
        ok = True
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
