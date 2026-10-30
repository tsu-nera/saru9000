"""The dance's blinking, sent to the SwitchBot Cloud API directly.

HA's switchbot_cloud integration sleeps 5 s after every light command, so a
beat-long blink cannot go through HA. Each beat is sent without waiting for the
reply (about 0.4 s). Calls are capped at 10000 a day per account, and HA and
Adaptive Lighting use the same account: one dance is a few hundred calls.
Stdlib only, like session.py; the keys come from the repo's .env via home/ha.py.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import sys
import time
import urllib.request
import uuid
from pathlib import Path

log = logging.getLogger("switchbot")

API = "https://api.switch-bot.com/v1.1"
TIMEOUT = 5
HA_DIR = str(Path(__file__).resolve().parents[2] / "home")
BULB_TYPE = "Color Bulb"
# ミクの色に、点滅で違いが目立つ黄を足す。The API takes "R:G:B".
COLORS = ("57:197:187", "255:40:150", "255:210:0")


def keys():
    if HA_DIR not in sys.path:
        sys.path.insert(0, HA_DIR)
    import ha

    try:
        return ha.secret("SWITCHBOT_TOKEN"), ha.secret("SWITCHBOT_SECRET")
    except SystemExit as e:
        raise RuntimeError(f"switchbot is not configured: {e}") from e


def headers(token, secret):
    t, nonce = str(int(time.time() * 1000)), uuid.uuid4().hex
    sign = hmac.new(secret.encode(), f"{token}{t}{nonce}".encode(), hashlib.sha256).digest()
    return {
        "Authorization": token,
        "sign": base64.b64encode(sign).decode(),
        "t": t,
        "nonce": nonce,
        "Content-Type": "application/json",
    }


def call(keys, method, path, body=None):
    request = urllib.request.Request(
        f"{API}{path}",
        method=method,
        headers=headers(*keys),
        data=None if body is None else json.dumps(body).encode(),
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as r:
        reply = json.loads(r.read())
    if reply.get("statusCode") != 100:
        raise RuntimeError(f"{path}: {reply}")
    return reply["body"]


def bulbs(keys):
    """The ids of every Color Bulb on the account (no ids in the repo: it is public)."""
    devices = call(keys, "GET", "/devices")["deviceList"]
    return [d["deviceId"] for d in devices if d["deviceType"] == BULB_TYPE]


def command(keys, device_id, name, parameter="default"):
    body = {"command": name, "parameter": parameter, "commandType": "command"}
    call(keys, "POST", f"/devices/{device_id}/commands", body)


def beat_commands(i):
    """[(command, parameter)] for beat i: off on even beats, the next color on odd ones.

    The first light-up also sets full brightness: before the blink starts the bulbs
    must stay off, and setBrightness turns a bulb on.
    """
    if i % 2 == 0:
        return [("turnOff", "default")]
    color = [("setColor", COLORS[(i // 2) % len(COLORS)])]
    return color + [("setBrightness", "100")] if i == 1 else color


async def blink(start, end, beat):
    """Blink every bulb each beat from start to end (loop times), then turn them off.

    Stops early when cancelled (the dance is over). Never raises.
    """
    try:
        k = await asyncio.to_thread(keys)
        ids = await asyncio.to_thread(bulbs, k)
    except Exception as e:
        log.warning("blink not started: %s: %s", type(e).__name__, e)
        return
    loop = asyncio.get_running_loop()
    sent = set()
    i = 0
    try:
        while start + i * beat < end:
            await asyncio.sleep(max(0.0, start + i * beat - loop.time()))
            for name, parameter in beat_commands(i):
                for b in ids:
                    _fire(sent, k, b, name, parameter)
            i += 1
        await asyncio.sleep(max(0.0, end - loop.time()))
        for b in ids:
            _fire(sent, k, b, "turnOff")
    finally:
        log.info("blinked %d beats", i)
        # Commands still in flight must land before the lights are put back.
        await asyncio.gather(*sent, return_exceptions=True)


def _fire(sent, k, device_id, name, parameter="default"):
    task = asyncio.create_task(_send(k, device_id, name, parameter))
    sent.add(task)
    task.add_done_callback(sent.discard)


async def _send(k, device_id, name, parameter):
    try:
        await asyncio.to_thread(command, k, device_id, name, parameter)
    except Exception as e:
        log.warning("%s %s failed: %s: %s", device_id, name, type(e).__name__, e)
