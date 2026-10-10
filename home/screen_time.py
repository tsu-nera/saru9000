"""mouse のアプリごとの使用時間（今日の分）を5分ごとに集計し、HA の sensor へ送る常駐スクリプト（vaio で動かす）。

go-hass-agent が送る sensor.cachyos_active_app の履歴を 04:00 から読み直し、アプリ名が入っていて
離席（binary_sensor.cachyos_idle）でも電源断（sensor.cachyos_power_state）でもない時間を足す。
毎回その日の頭から計算し直すので、途中で落ちても数字はずれない。HA に届かない回は捨てて続ける。

    python3 home/screen_time.py          # 普段は systemd --user の screen_time.service から起動
    python3 home/screen_time.py --once   # 1回だけ集計して送り、結果を JSON で出す
"""

import argparse
import json
import sys
import time
import urllib.parse
from datetime import datetime, timedelta

from ha import JST, rest

APP = "sensor.cachyos_active_app"
IDLE = "binary_sensor.cachyos_idle"
POWER = "sensor.cachyos_power_state"
NOT_AN_APP = {"none", "unavailable", "unknown", ""}
DAY_START_HOUR = 4
TOP = 5
SECONDS_PER_REPORT = 300
# app_id の最後の部分で足りないものだけ読み替える
NAMES = {"google-chrome": "Chrome", "vesktop": "Discord", "emacs": "Emacs", "com.mitchellh.ghostty": "Ghostty"}


def day_start(now: datetime) -> datetime:
    """now が属する「1日」の始まり（04:00 JST）。04:00 前は前日の 04:00。"""
    start = now.astimezone(JST).replace(hour=DAY_START_HOUR, minute=0, second=0, microsecond=0)
    return start - timedelta(days=1) if now.astimezone(JST) < start else start


def app_name(app_id: str) -> str:
    return NAMES.get(app_id, app_id.rsplit(".", 1)[-1])


def per_app(events: list[tuple[datetime, str, str]], start: datetime, end: datetime) -> dict[str, float]:
    """(時刻, entity_id, state) の列から、start〜end にアプリが前面で使われていた秒数をアプリ別に出す。

    期間の頭の state は start 以前の時刻で入っていてよい（history API は頭の値を start の時刻で返す）。
    """
    state = {APP: "none", IDLE: "off", POWER: "Powered On"}
    totals: dict[str, float] = {}
    t = start
    for at, entity_id, value in sorted(events) + [(end, "", "")]:
        at = min(max(at, start), end)
        app = state[APP]
        if at > t and app not in NOT_AN_APP and state[IDLE] != "on" and state[POWER] != "Powered Off":
            name = app_name(app)
            totals[name] = totals.get(name, 0.0) + (at - t).total_seconds()
        t = at
        if entity_id:
            state[entity_id] = value
    return totals


def fetch(start: datetime, end: datetime) -> list[tuple[datetime, str, str]]:
    q = urllib.parse.quote
    path = (f"/api/history/period/{q(start.isoformat())}?end_time={q(end.isoformat())}"
            f"&filter_entity_id={APP},{IDLE},{POWER}&minimal_response&no_attributes")
    events = []
    for series in json.loads(rest("GET", path, timeout=30)):
        entity_id = series[0]["entity_id"]
        events += [(datetime.fromisoformat(s["last_changed"]), entity_id, s["state"]) for s in series]
    return events


def report(totals: dict[str, float], start: datetime) -> dict:
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    top = [{"app": name, "minutes": round(sec / 60)} for name, sec in ranked[:TOP]]
    return {
        "minutes": round(sum(totals.values()) / 60),
        "most_used": top[0] if top else None,
        "top_apps": top,
        "day_start": start.isoformat(),
    }


def post_to_ha(r: dict) -> None:
    rest("POST", "/api/states/sensor.mouse_screen_time_today", {
        "state": r["minutes"],
        "attributes": {"unit_of_measurement": "min", "device_class": "duration", "state_class": "total_increasing",
                       "friendly_name": "mouse 画面時間（今日）", "icon": "mdi:monitor-dashboard",
                       "top_apps": r["top_apps"], "day_start": r["day_start"]},
    }, timeout=10)
    most = r["most_used"] or {"app": "なし", "minutes": 0}
    rest("POST", "/api/states/sensor.mouse_most_used_app_today", {
        "state": most["app"],
        "attributes": {"minutes": most["minutes"], "friendly_name": "mouse 一番使ったアプリ（今日）",
                       "icon": "mdi:application", "day_start": r["day_start"]},
    }, timeout=10)


def run_once() -> dict:
    now = datetime.now(JST)
    start = day_start(now)
    r = report(per_app(fetch(start, now), start, now), start)
    post_to_ha(r)
    return r


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    if parser.parse_args().once:
        print(json.dumps(run_once(), ensure_ascii=False, indent=1))
        return
    while True:
        try:
            run_once()
        except Exception as e:
            print(f"screen_time: failed, dropped this round: {e!r}", file=sys.stderr, flush=True)
        time.sleep(SECONDS_PER_REPORT)


if __name__ == "__main__":
    main()
