"""SwitchBot Cloud API v1.1 を直接叩く CLI。HA を経由しない確認・切り分け用（普段の操作は ha.py で HA から）。

署名は HMAC-SHA256(secret, token + t + nonce) を base64 したもの。キーは repo .env の
SWITCHBOT_TOKEN / SWITCHBOT_SECRET。API の上限は 1日 10,000 回（HA の polling と共有）。

    python3 home/switchbot.py devices
    python3 home/switchbot.py status <deviceId>
    python3 home/switchbot.py command <deviceId> turnOn|turnOff|setBrightness [parameter]
"""

import argparse
import base64
import hashlib
import hmac
import json
import time
import urllib.request
import uuid

from ha import CONFIG, secret


def request(method: str, path: str, body: dict | None = None) -> dict:
    token, key = secret("SWITCHBOT_TOKEN"), secret("SWITCHBOT_SECRET")
    t, nonce = str(int(time.time() * 1000)), str(uuid.uuid4())
    sign = base64.b64encode(hmac.new(key.encode(), (token + t + nonce).encode(), hashlib.sha256).digest()).decode()
    req = urllib.request.Request(
        f"{CONFIG['switchbot_api']}{path}",
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={"Authorization": token, "sign": sign, "t": t, "nonce": nonce,
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        res = json.load(r)
    if res["statusCode"] != 100:
        raise SystemExit(json.dumps(res, ensure_ascii=False))
    return res["body"]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("devices")
    s = sub.add_parser("status")
    s.add_argument("device_id")
    s = sub.add_parser("command")
    s.add_argument("device_id")
    s.add_argument("name")
    s.add_argument("parameter", nargs="?", default="default")
    args = p.parse_args()

    if args.command == "devices":
        out = request("GET", "/devices")
    elif args.command == "status":
        out = request("GET", f"/devices/{args.device_id}/status")
    else:
        out = request("POST", f"/devices/{args.device_id}/commands",
                      {"command": args.name, "parameter": args.parameter, "commandType": "command"})
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
