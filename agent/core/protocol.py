"""WebSocket messages between core and its clients (spec: issue #18).

Builders make the outgoing dicts; parse() validates an incoming text frame.
Anything invalid is logged and dropped so one bad client cannot stop the core.
"""

import base64
import json
import logging

logger = logging.getLogger(__name__)

# How heard sentences are answered: only when a wake word is in them, or all.
LISTEN_MODES = ("wake", "always")

# Incoming type -> {required field: expected type}.
INCOMING = {
    "text_input": {"text": str},
    "ready": {"avatar": str},
    "speak_started": {"id": int},
    "speak_ended": {"id": int},
    "motion_ended": {"name": str},
    "listen_mode": {"mode": str},
    "stop_motion": {},
}


def state(name):
    return {"type": "state", "state": name}


def listen_mode(mode):
    return {"type": "listen_mode", "mode": mode}


def utterance(who, text, name=None):
    """who is "user" or "agent"; name is the character shown for the agent."""
    message = {"type": "utterance", "who": who, "text": text}
    if name is not None:
        message["name"] = name
    return message


def speak(id, text, wav_bytes, visemes, expression=None):
    message = {
        "type": "speak",
        "id": id,
        "text": text,
        "wav": base64.b64encode(wav_bytes).decode("ascii"),
        "visemes": visemes,
    }
    if expression is not None:
        message["expression"] = expression
    return message


def expression(name):
    return {"type": "expression", "name": name}


def motion(name):
    return {"type": "motion", "name": name}


def stop_motion():
    return {"type": "stop_motion"}


def log(kind, text, append=False):
    """A line for the stage's screen; append continues the last line of the same kind."""
    return {"type": "log", "kind": kind, "text": text, "append": append}


def parse(raw):
    """Decode one incoming frame; None (after a warning) if it is not valid."""
    try:
        message = json.loads(raw)
    except ValueError:
        logger.warning("dropped message: not JSON: %.100r", raw)
        return None
    if not isinstance(message, dict):
        logger.warning("dropped message: not an object: %.100r", raw)
        return None
    kind = message.get("type")
    fields = INCOMING.get(kind)
    if fields is None:
        logger.warning("dropped message: unknown type %r", kind)
        return None
    for name, expected in fields.items():
        value = message.get(name)
        # bool is an int in Python but never a valid id.
        if not isinstance(value, expected) or isinstance(value, bool):
            logger.warning("dropped %s: missing or invalid field %r", kind, name)
            return None
    return message
