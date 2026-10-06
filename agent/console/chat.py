#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["claude-agent-sdk"]
# ///
"""Console chat with the saru9000 agent via the Claude Agent SDK.

Uses the Claude Code login (subscription), not API-key billing. Replies stream
token by token so the same loop can later feed VOICEVOX sentence by sentence.

    ./chat.py              # Claude Code's default model
    ./chat.py --model sonnet
"""

import argparse
import asyncio
import os
from pathlib import Path

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
)

PERSONA_PATH = Path(__file__).resolve().parent.parent / "bridge" / "persona.txt"


def build_options(model):
    return ClaudeAgentOptions(
        system_prompt=PERSONA_PATH.read_text(encoding="utf-8").strip(),
        tools=[],
        # Skip user/project CLAUDE.md and settings: they are for coding sessions
        # and only slow the first reply down.
        setting_sources=[],
        include_partial_messages=True,
        model=model,
    )


async def answer(client, text):
    await client.query(text)
    async for message in client.receive_response():
        if isinstance(message, StreamEvent):
            event = message.event
            if event.get("type") == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    print(delta["text"], end="", flush=True)
        elif isinstance(message, ResultMessage):
            print(f"\n  ({message.duration_ms / 1000:.1f}s)")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    # The SDK prefers ANTHROPIC_API_KEY over the Claude Code login when set.
    os.environ.pop("ANTHROPIC_API_KEY", None)

    async with ClaudeSDKClient(options=build_options(args.model)) as client:
        while True:
            try:
                text = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not text:
                continue
            print("miku> ", end="", flush=True)
            await answer(client, text)


if __name__ == "__main__":
    asyncio.run(main())
