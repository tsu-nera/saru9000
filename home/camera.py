"""vaio の部屋カメラ（go2rtc + HA の Generic Camera）を mouse から操作する。

オン/オフは go2rtc コンテナの起動・停止と、HA の generic config entry の有効・無効を揃えて切り替える
（片方だけだと HA が止まったストリームを叩き続ける）。照明が消えていると snap は真っ黒になる。

    python3 home/camera.py on|off|status
    python3 home/camera.py snap [-o snap.jpg]
"""

import argparse
import json
from pathlib import Path

from ha import CONFIG, rest, ssh, state, ws


def generic_entry() -> dict:
    entries = ws("config_entries/get", domain="generic")
    if len(entries) != 1:
        raise SystemExit(f"expected 1 generic entry, got {len(entries)}")
    return entries[0]


def set_entry(disabled_by: str | None):
    ws("config_entries/disable", entry_id=generic_entry()["entry_id"], disabled_by=disabled_by)


def status() -> dict:
    entry = generic_entry()
    return {
        "go2rtc": ssh(f"docker inspect -f '{{{{.State.Status}}}}' {CONFIG['go2rtc_container']}"),
        "ha_entry": {"entry_id": entry["entry_id"], "disabled_by": entry["disabled_by"]},
        "entity_state": state(CONFIG["camera_entity"])["state"],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["on", "off", "status", "snap"])
    p.add_argument("-o", "--output", default="snap.jpg", help="snap の保存先")
    args = p.parse_args()

    if args.command == "on":
        ssh(f"docker start {CONFIG['go2rtc_container']}")
        set_entry(None)
    elif args.command == "off":
        set_entry("user")
        ssh(f"docker stop {CONFIG['go2rtc_container']}")
    elif args.command == "snap":
        out = Path(args.output)
        out.write_bytes(rest("GET", f"/api/camera_proxy/{CONFIG['camera_entity']}"))
        print(out.resolve())
        return
    print(json.dumps(status(), ensure_ascii=False))


if __name__ == "__main__":
    main()
