"""The brain behind saru: turns what the user said into a stream of reply text.

Session and protocol only know TextDelta / Done. Claude types stay inside
ClaudeBrain, and claude_agent_sdk is imported lazily so the rest of the core
(and its tests) run without the SDK installed.
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Protocol

PERSONA_PATH = Path(__file__).resolve().parent / "persona.txt"
# private/ is gitignored: conversations stay out of the public repo.
LOG_DIR = Path(__file__).resolve().parents[2] / "private" / "chat-logs"

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


@dataclass
class TextDelta:
    text: str


@dataclass
class Done:
    model: str | None
    usage: dict


class Brain(Protocol):
    def reply(self, text: str) -> AsyncIterator[TextDelta | Done]: ...


def drop_api_key():
    # The SDK prefers ANTHROPIC_API_KEY over the Claude Code login when set.
    os.environ.pop("ANTHROPIC_API_KEY", None)


def build_options(model):
    from claude_agent_sdk import ClaudeAgentOptions

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


class ClaudeBrain:
    """Brain on a long-lived Claude Agent SDK session (Claude Code login)."""

    def __init__(self, model=DEFAULT_MODEL):
        self.model = model
        self.client = None

    async def __aenter__(self):
        from claude_agent_sdk import ClaudeSDKClient

        self.client = ClaudeSDKClient(options=build_options(self.model))
        await self.client.__aenter__()
        return self

    async def __aexit__(self, *exc):
        client, self.client = self.client, None
        if client is not None:
            return await client.__aexit__(*exc)

    async def reply(self, text):
        from claude_agent_sdk import AssistantMessage, ResultMessage, StreamEvent

        await self.client.query(text)
        model = None
        async for message in self.client.receive_response():
            if isinstance(message, StreamEvent):
                event = message.event
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        yield TextDelta(delta["text"])
            elif isinstance(message, AssistantMessage):
                model = message.model
            elif isinstance(message, ResultMessage):
                usage = message.usage or {}
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
                yield Done(model, usage)
