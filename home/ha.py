"""Home Assistant を mouse から操作する CLI 兼ライブラリ。出力は JSON。

REST で済むもの（状態・サービス呼び出し）は REST、registry や config entry の操作は websocket。
websocket は mouse に依存ライブラリを入れず、HA コンテナ内の python3 + aiohttp に ssh 越しの stdin で
スクリプトを渡して実行する（トークンを argv に出さない）。

    python3 home/ha.py states [--domain light] [--area mein]
    python3 home/ha.py state light.denkyu_hidari
    python3 home/ha.py call light.turn_on light.denkyu_hidari light.denkyu_migi [--data '{"brightness_pct": 50}']
    python3 home/ha.py ws config/entity_registry/update '{"entity_id": "light.x", "area_id": "mein"}'
"""

import argparse
import json
import os
import subprocess
import urllib.request
from pathlib import Path

HOME_DIR = Path(__file__).resolve().parent
CONFIG = json.loads((HOME_DIR / "config.json").read_text())


def repo_env_file() -> Path:
    """repo 直下の .env。worktree から呼ばれても main checkout の .env を指す。"""
    common = subprocess.run(
        ["git", "-C", str(HOME_DIR), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return Path(common).parent / ".env"


def secret(name: str) -> str:
    if name in os.environ:
        return os.environ[name]
    env = repo_env_file()
    for line in env.read_text().splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1]
    raise SystemExit(f"{name} not found in environment or {env}")


def ssh(command: str, stdin: str | None = None) -> str:
    r = subprocess.run(["ssh", CONFIG["ssh_host"], command], input=stdin, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"ssh {CONFIG['ssh_host']} {command!r} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def rest(method: str, path: str, body: dict | None = None, timeout: float = 60) -> bytes:
    req = urllib.request.Request(
        f"{CONFIG['ha_url']}{path}",
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={"Authorization": f"Bearer {secret('HA_TOKEN')}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


WS_RUNNER = """
import asyncio, json, sys, aiohttp
async def main():
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect("ws://127.0.0.1:8123/api/websocket") as ws:
            await ws.receive_json()
            await ws.send_json({"type": "auth", "access_token": TOKEN})
            if (await ws.receive_json())["type"] != "auth_ok":
                sys.exit("HA auth failed")
            results = []
            for i, msg in enumerate(MESSAGES, 1):
                await ws.send_json({"id": i, **msg})
                r = await ws.receive_json()
                if not r["success"]:
                    sys.exit(json.dumps({"request": msg, "error": r["error"]}, ensure_ascii=False))
                results.append(r["result"])
            print(json.dumps(results, ensure_ascii=False))
asyncio.run(main())
"""


def ws_batch(messages: list[dict]) -> list:
    """websocket コマンドを1接続で順に実行し、各 result を返す。1つでも失敗したら止まる。"""
    script = f"TOKEN = {secret('HA_TOKEN')!r}\nMESSAGES = {messages!r}\n" + WS_RUNNER
    return json.loads(ssh(f"docker exec -i {CONFIG['ha_container']} python3 -", stdin=script))


def ws(type_: str, **payload):
    return ws_batch([{"type": type_, **payload}])[0]


def state(entity_id: str) -> dict:
    return json.loads(rest("GET", f"/api/states/{entity_id}"))


def call(service: str, entity_ids: list[str], data: dict) -> list:
    domain, name = service.split(".", 1)
    body = {**data, **({"entity_id": entity_ids} if entity_ids else {})}
    return json.loads(rest("POST", f"/api/services/{domain}/{name}", body, timeout=120))


def states(domain: str | None, area: str | None) -> list[dict]:
    entities, devices = ws_batch([
        {"type": "config/entity_registry/list"},
        {"type": "config/device_registry/list"},
    ])
    device_area = {d["id"]: d["area_id"] for d in devices}
    reg = {e["entity_id"]: e["area_id"] or device_area.get(e["device_id"]) for e in entities}
    rows = []
    for s in json.loads(rest("GET", "/api/states")):
        eid = s["entity_id"]
        if domain and not eid.startswith(f"{domain}."):
            continue
        if area and reg.get(eid) != area:
            continue
        rows.append({"entity_id": eid, "state": s["state"],
                     "name": s["attributes"].get("friendly_name"), "area": reg.get(eid)})
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("states", help="entity の一覧（area は entity → device の順に解決）")
    s.add_argument("--domain")
    s.add_argument("--area", help="area_id（例: mein）")
    s = sub.add_parser("state", help="1 entity の state と attributes")
    s.add_argument("entity_id")
    s = sub.add_parser("call", help="サービス呼び出し。変化した state を返す")
    s.add_argument("service", help="domain.service（例: light.turn_on）")
    s.add_argument("entity_ids", nargs="*")
    s.add_argument("--data", default="{}", help="追加の service data（JSON）")
    s = sub.add_parser("ws", help="websocket コマンドを1つ実行")
    s.add_argument("type", help="例: config/entity_registry/update")
    s.add_argument("payload", nargs="?", default="{}", help="JSON")
    args = p.parse_args()

    if args.command == "states":
        out = states(args.domain, args.area)
    elif args.command == "state":
        out = state(args.entity_id)
    elif args.command == "call":
        out = call(args.service, args.entity_ids, json.loads(args.data))
    else:
        out = ws(args.type, **json.loads(args.payload))
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
