"""vaio の部屋カメラ（go2rtc + HA の Generic Camera）を mouse から操作する。

オン/オフは go2rtc コンテナの起動・停止と、HA の generic config entry の有効・無効を揃えて切り替える
（片方だけだと HA が止まったストリームを叩き続ける）。HA の entry 操作は websocket にしか無いので、
HA コンテナ内の python3 + aiohttp に stdin でスクリプトを渡して実行する。トークンは repo の .env の HA_TOKEN。

    python3 camera.py on|off|status
    python3 camera.py snap [-o snap.jpg]
"""

import argparse
import json
import subprocess
import urllib.request
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

WS_SCRIPT = """
import asyncio, json, aiohttp
async def main():
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect("ws://127.0.0.1:8123/api/websocket") as ws:
            await ws.receive_json()
            await ws.send_json({"type": "auth", "access_token": TOKEN})
            if (await ws.receive_json())["type"] != "auth_ok":
                raise SystemExit("HA auth failed")
            await ws.send_json({"id": 1, "type": "config_entries/get", "domain": "generic"})
            entries = (await ws.receive_json())["result"]
            if len(entries) != 1:
                raise SystemExit(f"expected 1 generic entry, got {len(entries)}")
            entry = entries[0]
            if DISABLED_BY != "keep":
                await ws.send_json({"id": 2, "type": "config_entries/disable",
                                    "entry_id": entry["entry_id"], "disabled_by": DISABLED_BY})
                res = await ws.receive_json()
                if not res["success"]:
                    raise SystemExit(json.dumps(res))
                entry["disabled_by"] = DISABLED_BY
            print(json.dumps({"entry_id": entry["entry_id"], "disabled_by": entry["disabled_by"]}))
asyncio.run(main())
"""


def ha_token() -> str:
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("HA_TOKEN="):
            return line.split("=", 1)[1]
    raise SystemExit(f"HA_TOKEN not found in {ENV_FILE}")


def ssh(args: argparse.Namespace, command: str, stdin: str | None = None) -> str:
    r = subprocess.run(["ssh", args.host, command], input=stdin, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"ssh {args.host} {command!r} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def ha_entry(args: argparse.Namespace, disabled_by: str | None) -> dict:
    """disabled_by: None で有効化、"user" で無効化、"keep" で読むだけ。"""
    script = f"TOKEN = {ha_token()!r}\nDISABLED_BY = {disabled_by!r}\n" + WS_SCRIPT
    return json.loads(ssh(args, f"docker exec -i {args.ha_container} python3 -", stdin=script))


def go2rtc_state(args: argparse.Namespace) -> str:
    return ssh(args, f"docker inspect -f '{{{{.State.Status}}}}' {args.go2rtc_container}")


def ha_get(args: argparse.Namespace, path: str) -> bytes:
    req = urllib.request.Request(
        f"{args.ha_url}{path}", headers={"Authorization": f"Bearer {ha_token()}"}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def status(args: argparse.Namespace) -> dict:
    state = json.loads(ha_get(args, f"/api/states/{args.entity}"))["state"]
    return {
        "go2rtc": go2rtc_state(args),
        "ha_entry": ha_entry(args, "keep"),
        "entity_state": state,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["on", "off", "status", "snap"])
    p.add_argument("-o", "--output", default="snap.jpg", help="snap の保存先")
    p.add_argument("--host", default="vaio")
    p.add_argument("--ha-url", default="http://vaio.tail144b9c.ts.net:8123")
    p.add_argument("--ha-container", default="homeassistant")
    p.add_argument("--go2rtc-container", default="go2rtc")
    p.add_argument("--entity", default="camera.heya_camera")
    args = p.parse_args()

    if args.command == "on":
        ssh(args, f"docker start {args.go2rtc_container}")
        ha_entry(args, None)
    elif args.command == "off":
        ha_entry(args, "user")
        ssh(args, f"docker stop {args.go2rtc_container}")
    elif args.command == "snap":
        out = Path(args.output)
        out.write_bytes(ha_get(args, f"/api/camera_proxy/{args.entity}"))
        print(out.resolve())
        return
    print(json.dumps(status(args), ensure_ascii=False))


if __name__ == "__main__":
    main()
