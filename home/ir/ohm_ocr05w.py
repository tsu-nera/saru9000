"""OHM リモコンコンセント OCR-05W を Nature Remo のローカル API から生信号で操作する。

信号形式（2ソースで一致）: キャリア 38kHz、リーダー on/off 約2600µs、8bit LSB first、
ビットは on 約800µs + off 約800µs(0) / 約1800µs(1)、末尾 on 約800µs。ON=0x3C、OFF=0xD2。

    python3 ohm_ocr05w.py on|off [--remo 192.168.100.252] [--repeat 3] [--dry-run]
"""

import argparse
import json
import urllib.request

CODES = {"on": 0x3C, "off": 0xD2}
LEADER = 2600
MARK = 800
SPACE_0 = 800
SPACE_1 = 1800
GAP = 20000


def frame(code: int) -> list[int]:
    data = [LEADER, LEADER]
    for i in range(8):
        data += [MARK, SPACE_1 if code >> i & 1 else SPACE_0]
    return data + [MARK]


def signal(code: int, repeat: int) -> list[int]:
    data = []
    for _ in range(repeat):
        if data:
            data.append(GAP)
        data += frame(code)
    return data


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=CODES)
    p.add_argument("--remo", default="192.168.100.252")
    p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    body = {"freq": 38, "data": signal(CODES[args.command], args.repeat), "format": "us"}
    if args.dry_run:
        print(json.dumps(body))
        return
    req = urllib.request.Request(
        f"http://{args.remo}/messages",
        data=json.dumps(body).encode(),
        headers={"X-Requested-With": "local", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        print(r.status)


if __name__ == "__main__":
    main()
