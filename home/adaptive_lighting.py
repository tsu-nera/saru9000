"""Adaptive Lighting（時間帯で電球の色温度・明るさを変える custom integration）の設定を mouse から見る・変える。

設定は HA の options flow にしか無いので、現在値を既定値として読み、指定した項目だけ上書きして送り直す。
`advanced` 配下（brightness_mode・take_over_control 等）は `{"advanced": {...}}` で渡す。

    python3 home/adaptive_lighting.py show
    python3 home/adaptive_lighting.py set '{"min_brightness": 40, "advanced": {"brightness_mode": "tanh"}}'
"""

import argparse
import json

from ha import rest, state, ws

SWITCH = "switch.adaptive_lighting_denkyu"


def entry_id() -> str:
    entries = ws("config_entries/get", domain="adaptive_lighting")
    if len(entries) != 1:
        raise SystemExit(f"expected 1 adaptive_lighting entry, got {len(entries)}")
    return entries[0]["entry_id"]


def current(flow: dict) -> dict:
    options = {}
    for field in flow["data_schema"]:
        if field["name"] == "advanced":
            options["advanced"] = {f["name"]: f.get("default") for f in field["schema"]}
        else:
            options[field["name"]] = field.get("default")
    return options


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["show", "set"])
    p.add_argument("options", nargs="?", help="set で上書きする項目（JSON）")
    args = p.parse_args()

    flow = json.loads(rest("POST", "/api/config/config_entries/options/flow", {"handler": entry_id()}))
    options = current(flow)
    if args.command == "show":
        rest("DELETE", f"/api/config/config_entries/options/flow/{flow['flow_id']}")
        attrs = state(SWITCH)["attributes"]
        target = {k: attrs.get(k) for k in ("brightness_pct", "color_temp_kelvin", "sun_position", "manual_control")}
        print(json.dumps({"options": options, "target": target}, ensure_ascii=False, indent=1))
        return

    override = json.loads(args.options)
    options["advanced"].update(override.pop("advanced", {}))
    options.update(override)
    result = json.loads(rest("POST", f"/api/config/config_entries/options/flow/{flow['flow_id']}", options))
    if result.get("type") != "create_entry":
        raise SystemExit(json.dumps(result, ensure_ascii=False))
    print(json.dumps({k: v for k, v in options.items() if k != "advanced"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
