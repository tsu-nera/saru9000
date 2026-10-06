#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["claude-agent-sdk"]
# ///
"""Console chat with the saru9000 agent via the Claude Agent SDK.

Uses the Claude Code login (subscription), not API-key billing. Replies stream
token by token so the same loop can later feed VOICEVOX sentence by sentence.

    ./chat.py              # sonnet
    ./chat.py --model opus
"""

import argparse
import asyncio
import os
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
)

PERSONA_PATH = Path(__file__).resolve().parent.parent / "bridge" / "persona.txt"

# Pinned rather than left to Claude Code: setting_sources=[] skips the user's
# settings.json, so the fallback would be the plan's default model.
DEFAULT_MODEL = "sonnet"


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
    model = None
    async for message in client.receive_response():
        if isinstance(message, StreamEvent):
            event = message.event
            if event.get("type") == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    print(delta["text"], end="", flush=True)
        elif isinstance(message, AssistantMessage):
            model = message.model
        elif isinstance(message, ResultMessage):
            print(f"\n  ({message.duration_ms / 1000:.1f}s, {model})")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
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
