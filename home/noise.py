"""vaio のマイクで部屋の音の大きさを常時測り、1分ごとに HA の sensor へ送る常駐スクリプト（vaio 専用）。

pw-record の生 PCM を stdout で受け、1秒ごとの RMS を dBFS にし、1分ぶんから Leq・max・L90 を出して
sensor.noise_leq / sensor.noise_max / sensor.noise_l90 に POST する。録音は保存せず、マイクの設定も触らない。
HA に届かない1分は捨てて続け、pw-record が終わったら非0で抜けて systemd に再起動を任せる。

    python3 home/noise.py   # 普段は systemd --user の noise.service から起動
"""

import math
import subprocess
import sys
from array import array
from typing import BinaryIO, Callable

from ha import rest

RATE = 16000
SAMPLE_BYTES = 2
FULL_SCALE = 32768
FLOOR_DB = -120.0
SECONDS_PER_REPORT = 60
RECORD = ["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16", "--raw", "-"]
SENSORS = {
    "leq": ("sensor.noise_leq", "騒音 Leq"),
    "max": ("sensor.noise_max", "騒音 max"),
    "l90": ("sensor.noise_l90", "騒音 L90"),
}


def dbfs(samples: array) -> float:
    """サンプル列の RMS を dBFS にする。無音は FLOOR_DB。"""
    if not samples:
        return FLOOR_DB
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    if rms == 0:
        return FLOOR_DB
    return max(FLOOR_DB, 20 * math.log10(rms / FULL_SCALE))


def summarize(levels: list[float]) -> dict[str, float]:
    """1秒値の列から Leq（エネルギー平均）・max・L90（下位10%点、nearest-rank）を出す。"""
    leq = 10 * math.log10(sum(10 ** (db / 10) for db in levels) / len(levels))
    ranked = sorted(levels)
    l90 = ranked[max(0, math.ceil(len(ranked) * 0.1) - 1)]
    return {"leq": leq, "max": ranked[-1], "l90": l90}


def measure(stream: BinaryIO, post: Callable[[dict[str, float]], None],
            seconds_per_report: int = SECONDS_PER_REPORT) -> None:
    """stream が尽きるまで1秒ずつ読み、seconds_per_report 秒ごとに post する。post の失敗はその回だけ捨てる。"""
    chunk = RATE * SAMPLE_BYTES
    levels: list[float] = []
    while len(data := stream.read(chunk)) == chunk:
        levels.append(dbfs(array("h", data)))
        if len(levels) < seconds_per_report:
            continue
        summary = summarize(levels)
        levels = []
        try:
            post(summary)
        except Exception as e:
            print(f"noise: post failed, dropped this minute: {e!r}", file=sys.stderr, flush=True)


def post_to_ha(summary: dict[str, float]) -> None:
    for key, (entity_id, name) in SENSORS.items():
        rest("POST", f"/api/states/{entity_id}", {
            "state": round(summary[key], 1),
            "attributes": {"unit_of_measurement": "dBFS", "state_class": "measurement", "friendly_name": name},
        }, timeout=10)


def main() -> None:
    rec = subprocess.Popen(RECORD, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
    try:
        measure(rec.stdout, post_to_ha)
    finally:
        rec.kill()
        rec.wait()
    sys.exit("noise: pw-record ended")


if __name__ == "__main__":
    main()
