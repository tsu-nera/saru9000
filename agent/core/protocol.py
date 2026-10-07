"""WebSocket messages between saru-core and its clients (spec: issue #18).

Builders make the outgoing dicts; parse() validates an incoming text frame.
Anything invalid is logged and dropped so one bad client cannot stop the core.
"""

import base64
import json
import logging

log = logging.getLogger(__name__)

# Incoming type -> {required field: expected type}.
INCOMING = {
    "text_input": {"text": str},
    "ready": {"avatar": str},
    "speak_started": {"id": int},
    "speak_ended": {"id": int},
    "motion_ended": {"name": str},
}


def state(name):
    return {"type": "state", "state": name}


def utterance(who, text):
    return {"type": "utterance", "who": who, "text": text}


def speak(id, text, wav_bytes, visemes):
    return {
        "type": "speak",
        "id": id,
        "text": text,
        "wav": base64.b64encode(wav_bytes).decode("ascii"),
        "visemes": visemes,
    }


def parse(raw):
    """Decode one incoming frame; None (after a warning) if it is not valid."""
    try:
        message = json.loads(raw)
    except ValueError:
        log.warning("dropped message: not JSON: %.100r", raw)
        return None
    if not isinstance(message, dict):
        log.warning("dropped message: not an object: %.100r", raw)
        return None
    kind = message.get("type")
    fields = INCOMING.get(kind)
    if fields is None:
        log.warning("dropped message: unknown type %r", kind)
        return None
    for name, expected in fields.items():
        value = message.get(name)
        # bool is an int in Python but never a valid id.
        if not isinstance(value, expected) or isinstance(value, bool):
            log.warning("dropped %s: missing or invalid field %r", kind, name)
            return None
    return message
