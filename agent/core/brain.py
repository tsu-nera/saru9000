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

# private/ is gitignored: conversations stay out of the public repo.
LOG_DIR = Path(__file__).resolve().parents[2] / "private" / "chat-logs"

# Pinned rather than left to Claude Code: setting_sources=[] skips the user's
# settings.json, so the fallback would be the plan's default model.
DEFAULT_MODEL = "sonnet"

# Claude Code adds these to every turn even with tools=[] and setting_sources=[]:
# the claude.ai connectors (Gmail, Slack, Drive, ...) came to ~64K input tokens
# per turn, and auto memory injected the dev notes of whatever repo the
# brain was started from.
ISOLATION_ENV = {
    "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
}

# The in-process MCP server that carries tools.registry; Claude sees its tools
# as mcp__core__<name>.
TOOL_SERVER = "core"


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


def allowed_tools(registry):
    return [f"mcp__{TOOL_SERVER}__{tool.name}" for tool in registry]


def option_fields(model, registry, persona):
    """ClaudeAgentOptions fields except mcp_servers, which needs the SDK."""
    return dict(
        system_prompt=persona,
        # No built-in tools (Bash, Read, ...); the registry's tools are allowed
        # without asking.
        tools=[],
        allowed_tools=allowed_tools(registry),
        # Skip user/project CLAUDE.md and settings: they are for coding sessions
        # and only slow the first reply down.
        setting_sources=[],
        # Ignore MCP servers configured for coding sessions.
        strict_mcp_config=True,
        env=ISOLATION_ENV,
        include_partial_messages=True,
        model=model,
    )


def _mcp_tool(tool):
    from claude_agent_sdk import SdkMcpTool

    async def handler(args):
        text = await tool.handler(args)
        return {"content": [{"type": "text", "text": text}]}

    return SdkMcpTool(tool.name, tool.description, tool.input_schema, handler)


def build_options(model, persona, registry=()):
    from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server

    server = create_sdk_mcp_server(TOOL_SERVER, tools=[_mcp_tool(tool) for tool in registry])
    return ClaudeAgentOptions(**option_fields(model, registry, persona), mcp_servers={TOOL_SERVER: server})


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

    def __init__(self, persona, model=DEFAULT_MODEL, registry=()):
        self.persona = persona  # system prompt
        self.model = model
        self.registry = registry  # tools.Tool list
        self.client = None

    async def __aenter__(self):
        from claude_agent_sdk import ClaudeSDKClient

        self.client = ClaudeSDKClient(options=build_options(self.model, self.persona, self.registry))
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
