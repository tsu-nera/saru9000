#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["claude-agent-sdk"]
# ///
"""Console chat with the saru9000 agent via the Claude Agent SDK.

Uses the Claude Code login (subscription), not API-key billing. Replies stream
token by token so the same loop can later feed VOICEVOX sentence by sentence.
Each turn is appended to private/chat-logs/YYYY-MM-DD.jsonl.

    ./chat.py              # sonnet
    ./chat.py --model opus
"""

import argparse
import asyncio
import json
import os
import signal
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
)

CONSOLE_DIR = Path(__file__).resolve().parent
PERSONA_PATH = CONSOLE_DIR / "persona.txt"
# private/ is gitignored: conversations stay out of the public repo.
LOG_DIR = CONSOLE_DIR.parent.parent / "private" / "chat-logs"

# Pinned rather than left to Claude Code: setting_sources=[] skips the user's
# settings.json, so the fallback would be the plan's default model.
DEFAULT_MODEL = "sonnet"

# Claude Code adds these to every turn even with tools=[] and setting_sources=[]:
# the claude.ai connectors (Gmail, Slack, Drive, ...) came to ~64K input tokens
# per turn, and auto memory injected the dev notes of whatever repo chat.py
# was started from.
ISOLATION_ENV = {
    "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
}


def build_options(model):
    return ClaudeAgentOptions(
        system_prompt=PERSONA_PATH.read_text(encoding="utf-8").strip(),
        tools=[],
        # Skip user/project CLAUDE.md and settings: they are for coding sessions
        # and only slow the first reply down.
        setting_sources=[],
        # Ignore MCP servers configured for coding sessions.
        strict_mcp_config=True,
        env=ISOLATION_ENV,
        include_partial_messages=True,
        model=model,
    )


def input_tokens(usage):
    return sum(
        usage.get(key, 0)
        for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    )


def append_log(record):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"{datetime.now():%Y-%m-%d}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


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


async def chat(model):
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
            await answer(client, text)


def raise_keyboard_interrupt(signum, frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    # The SDK prefers ANTHROPIC_API_KEY over the Claude Code login when set.
    os.environ.pop("ANTHROPIC_API_KEY", None)

    # asyncio.run turns the first Ctrl-C into a cancellation of the main task,
    # which a blocking input() never lets the loop process: the chat hangs and
    # the second Ctrl-C dumps tracebacks. A plain KeyboardInterrupt unwinds
    # through the client's async with, which shuts the CLI down cleanly.
    # asyncio.run only installs its handler over default_int_handler, so a
    # distinct function keeps it out.
    signal.signal(signal.SIGINT, raise_keyboard_interrupt)
    try:
        asyncio.run(chat(args.model))
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
