"""Ask Home Assistant's conversation API whether a sentence is one of its voice commands.

The rules (sentence triggers) and the replies live in HA, in
home/packages/voice_commands.yaml. The top of this module is stdlib only; the
HA client (home/ha.py reads config.json at import) is imported when asked.
"""

import asyncio
import json
import sys
from pathlib import Path

# The built-in rule-based agent: matches sentence triggers, never calls an LLM.
AGENT_ID = "conversation.home_assistant"
# Seconds. HA answers in well under a second; this bounds a dead connection.
TIMEOUT = 10


def parse(body):
    """The reply text of a conversation response, or None when HA understood nothing."""
    response = body["response"]
    if response.get("response_type") == "error":
        return None
    return response["speech"]["plain"]["speech"]


def call_ha(text):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "home"))
    try:
        import ha

        payload = {"text": text, "language": "ja", "agent_id": AGENT_ID}
        return ha.rest("POST", "/api/conversation/process", payload, TIMEOUT)
    except SystemExit as e:
        # ha.secret() exits when HA_TOKEN is missing; that must not stop the server.
        raise RuntimeError(f"home assistant is not configured: {e}") from e


async def ask(text):
    """HA's reply to `text`, or None when no sentence trigger matched."""
    return parse(json.loads(await asyncio.to_thread(call_ha, text)))
