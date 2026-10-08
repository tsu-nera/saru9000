"""Matter Hub（HA の entity を Google Home に見せるブリッジ）を mouse から確認・反映する。

公開対象は HA の entity ラベル `matter`。ラベルを付け外ししただけでは公開数が変わらないことがある。
Hub を再起動して増えた機器は Google Home で Offline のままになる（Google が読み直さない）。
`kick` は動作中に無害な entity を一時的に公開して（filter の更新で Hub が公開対象を作り直す）
Google に読み直させ、filter を元に戻す。ラベルを変えた後もこれで反映する。

    python3 home/matter_hub.py devices
    python3 home/matter_hub.py kick [--entity sensor.remo_nature_remo_remo_temperature] [--hold 90]
"""

import argparse
import base64
import json
import time
import urllib.request

from ha import CONFIG, secret

KICK_ENTITY = "sensor.remo_nature_remo_remo_temperature"


def api(method: str, path: str, body: dict | None = None):
    auth = base64.b64encode(f"admin:{secret('HAMH_HTTP_AUTH_PASSWORD')}".encode()).decode()
    req = urllib.request.Request(
        f"{CONFIG['matter_hub_url']}/api/matter{path}",
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def bridge() -> dict:
    bridges = api("GET", "/bridges")
    if len(bridges) != 1:
        raise SystemExit(f"expected 1 bridge, got {len(bridges)}")
    return bridges[0]


def devices() -> list[dict]:
    root = api("GET", f"/bridges/{bridge()['id']}/devices")
    rows = []
    for part in root["parts"][0]["parts"]:
        info = part["state"].get("bridgedDeviceBasicInformation", {})
        rows.append({"endpoint": part["id"]["local"], "name": info.get("nodeLabel"),
                     "reachable": info.get("reachable"), "on": part["state"].get("onOff", {}).get("onOff")})
    return rows


def put_filter(b: dict, include: list[dict]):
    api("PUT", f"/bridges/{b['id']}",
        {"id": b["id"], "name": b["name"], "port": b["port"], "filter": {**b["filter"], "include": include}})


def kick(entity: str, hold: int):
    b = bridge()
    original = b["filter"]["include"]
    put_filter(b, original + [{"type": "pattern", "value": entity}])
    try:
        time.sleep(hold)
    finally:
        # 外した endpoint は Hub の猶予（300 秒）の後に消える
        put_filter(b, original)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("devices", help="公開中の機器と reachable")
    s = sub.add_parser("kick", help="Google Home に機器一覧を読み直させる")
    s.add_argument("--entity", default=KICK_ENTITY, help="一時的に公開する無害な entity")
    s.add_argument("--hold", type=int, default=90, help="公開しておく秒数")
    args = p.parse_args()

    if args.command == "kick":
        kick(args.entity, args.hold)
    print(json.dumps(devices(), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
