#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["claude-agent-sdk", "sherpa-onnx>=1.13.8", "numpy"]
# ///
"""Console chat with the saru9000 agent via the Claude Agent SDK.

Uses the Claude Code login (subscription), not API-key billing. Replies stream
token by token; with --speak they are read aloud chunk by chunk with VOICEVOX
(see speech.py). Each turn is appended to private/chat-logs/YYYY-MM-DD.jsonl.

    ./chat.py              # sonnet
    ./chat.py --model opus
    ./chat.py --speak
    ./chat.py --listen                  # hear the user through the mic (see agent/core/listen.py)
    ./chat.py --listen --speak          # talk by voice both ways
    ./chat.py --listen --audio-in a.wav # feed wav files instead of the mic
"""

import argparse
import asyncio
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
)

# speech.py, brain.py and listen.py live in agent/core. Temporary: #27 replaces this
# script with a client of saru-core and removes it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

import listen  # noqa: E402
import speech  # noqa: E402
from brain import DEFAULT_MODEL, append_log, build_options, drop_api_key, input_tokens  # noqa: E402


async def answer(client, text, voicevox=None):
    pipeline = speech.SpeechPipeline(voicevox) if voicevox else None
    try:
        await reply(client, text, pipeline)
        if pipeline:
            # Wait for the voice so the next prompt does not talk over it.
            error = await pipeline.finish()
            if error:
                print(f"  (speech failed: {error})")
    finally:
        if pipeline:
            pipeline.cancel()


async def reply(client, text, pipeline):
    await client.query(text)
    model = None
    async for message in client.receive_response():
        if isinstance(message, StreamEvent):
            event = message.event
            if event.get("type") == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    print(delta["text"], end="", flush=True)
                    if pipeline:
                        pipeline.feed(delta["text"])
        elif isinstance(message, AssistantMessage):
            model = message.model
        elif isinstance(message, ResultMessage):
            usage = message.usage or {}
            print(
                f"\n  ({message.duration_ms / 1000:.1f}s, {model}, "
                f"in {input_tokens(usage)} / out {usage.get('output_tokens', 0)})"
            )
            append_log(
                {
                    "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "session_id": message.session_id,
                    "model": model,
                    "user": text,
                    "reply": message.result,
                    "duration_ms": message.duration_ms,
                    "usage": usage,
                }
            )


async def chat(model, voicevox):
    async with ClaudeSDKClient(options=build_options(model)) as client:
        while True:
            try:
                text = input("you> ").strip()
            except EOFError:
                print()
                return
            if not text:
                continue
            print("saru> ", end="", flush=True)
            await answer(client, text, voicevox)


async def heard(listener, audio_in, queue_task):
    """Yield what the user said: wav files in order, or the microphone queue."""
    if audio_in:
        async for text in listen.utterances(listener, listen.wav_blocks(audio_in)):
            yield text
        return
    queue, task = queue_task
    while True:
        get = asyncio.ensure_future(queue.get())
        # Also wait on the pump so that a dead microphone ends the chat loudly.
        await asyncio.wait({get, task}, return_when=asyncio.FIRST_COMPLETED)
        if not get.done():
            get.cancel()
            task.result()
            return
        yield get.result()


async def chat_by_voice(model, voicevox, audio_in):
    listener = listen.open_listener()
    queue = asyncio.Queue()
    task = None
    if not audio_in:
        task = asyncio.create_task(listen.pump(listener, listen.microphone(), queue))
    print("(listening...)", flush=True)
    try:
        async with ClaudeSDKClient(options=build_options(model)) as client:
            async for text in heard(listener, audio_in, (queue, task)):
                print(f"you> {text}")
                print("saru> ", end="", flush=True)
                # Half duplex: the mic keeps being read but the paused listener
                # drops it, so saru's own voice is never heard.
                listener.pause()
                await answer(client, text, voicevox)
                listener.resume()
                # Texts queued before/while answering are stale.
                while not queue.empty():
                    queue.get_nowait()
    finally:
        if task:
            task.cancel()


def raise_keyboard_interrupt(signum, frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--speak", action="store_true", help="read replies aloud with VOICEVOX")
    parser.add_argument("--listen", action="store_true", help="hear the user through the mic with ReazonSpeech")
    parser.add_argument(
        "--audio-in",
        action="append",
        metavar="WAV",
        help="feed 16 kHz mono 16-bit wav files instead of the mic; exits when all are played",
    )
    args = parser.parse_args()
    if args.audio_in and not args.listen:
        parser.error("--audio-in requires --listen")

    voicevox = None
    if args.speak:
        voicevox = speech.Voicevox(
            url=os.environ.get("VOICEVOX_URL", speech.DEFAULT_URL),
            speaker=int(os.environ.get("VOICEVOX_SPEAKER", speech.DEFAULT_SPEAKER)),
            speed=float(os.environ.get("VOICEVOX_SPEED", speech.DEFAULT_SPEED)),
        )

    drop_api_key()

    # asyncio.run turns the first Ctrl-C into a cancellation of the main task,
    # which a blocking input() never lets the loop process: the chat hangs and
    # the second Ctrl-C dumps tracebacks. A plain KeyboardInterrupt unwinds
    # through the client's async with, which shuts the CLI down cleanly.
    # asyncio.run only installs its handler over default_int_handler, so a
    # distinct function keeps it out.
    signal.signal(signal.SIGINT, raise_keyboard_interrupt)
    try:
        if args.listen:
            asyncio.run(chat_by_voice(args.model, voicevox, args.audio_in))
        else:
            asyncio.run(chat(args.model, voicevox))
    except KeyboardInterrupt:
        print()
    except (ValueError, RuntimeError) as e:
        # Bad wav or a dead microphone from listen.py.
        raise SystemExit(f"chat.py: {e}")


if __name__ == "__main__":
    main()
