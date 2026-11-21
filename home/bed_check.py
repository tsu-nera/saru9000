"""起床の判定: Tapo C220 で1枚撮り、丸めた寝袋が片付けてあるかを claude -p に答えさせて HA の input_select.ohayo_bed に書く。

スマートおはよう（packages/smart_ohayo.yaml）が鳴動の 10 分後に bed_check.sh 経由で vaio 上で呼ぶ。
撮る間だけ privacy mode を切り、画像は判定後に消す（残すのは判定結果だけ）。

    python3 home/bed_check.py [--keep IMAGE]   # --keep は手で確かめる時だけ。画像を残す
"""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from camera import ptz, snap_tapo
from ha import call

PRIVACY = "switch.tapo_c220_privacy"
RESULT = "input_select.ohayo_bed"
# privacy mode を切ってから 3 秒では赤外線に切り替わる前で真っ黒、11 秒で写った（2026-11-21）
SETTLE_AFTER_PRIVACY_OFF = 15
# 下いっぱいで部屋の北側の床（寝る場所）と、寝袋を立てて置く棚の横が入る。privacy mode で向きが変わるかは未確認なので毎回向け直す
TILT_DOWN_TIMES = 5

PROMPT = """{path} を Read で見て答えてください。

一人暮らしの部屋を窓側の天井近くから玄関の方へ見下ろした赤外線カメラ（白黒）の画像です。
片付けた寝袋は、白い寝袋を丸めて黒いベルトで留め、画面の左手前（棚の横）に縦に立てて置きます。
寝ている間は、寝袋を部屋の床に広げています。

丸めた寝袋が左手前に立てて置いてあれば yes、無い・床に広がっている・判断できないなら no。
yes か no の1語だけを答えてください。"""


def judge(image: Path) -> str:
    """claude -p に画像を見せて 'yes' / 'no' を返す。それ以外の返事は例外。"""
    claude = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
    # claude.ai のコネクタと auto memory を入れない（memory の agent-sdk-isolation）
    env = {**os.environ, "ENABLE_CLAUDEAI_MCP_SERVERS": "false", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
    r = subprocess.run(
        [claude, "-p", PROMPT.format(path=image), "--model", "sonnet", "--allowedTools", "Read",
         "--strict-mcp-config", "--output-format", "text"],
        cwd=image.parent, env=env, capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL,
    )
    if r.returncode != 0:
        raise RuntimeError(f"claude failed: {r.stderr.strip()[:300]}")
    return parse_answer(r.stdout)


def parse_answer(text: str) -> str:
    words = text.strip().lower().strip(".。 ").split()
    if len(words) == 1 and words[0] in ("yes", "no"):
        return words[0]
    raise RuntimeError(f"unexpected answer: {text.strip()[:100]!r}")


def snap_with_privacy_off() -> bytes:
    call("switch.turn_off", [PRIVACY], {})
    try:
        ptz("down", TILT_DOWN_TIMES, 1.0)
        time.sleep(SETTLE_AFTER_PRIVACY_OFF)
        return snap_tapo()
    finally:
        call("switch.turn_on", [PRIVACY], {})


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--keep", help="画像をこのパスに残す（手で確かめる時だけ）")
    args = p.parse_args()

    workdir = Path(tempfile.mkdtemp(prefix="bed-check-"))
    image = workdir / "snap.jpg"
    try:
        image.write_bytes(snap_with_privacy_off())
        if args.keep:
            shutil.copy(image, args.keep)
        answer = judge(image)
        option = "片付けた" if answer == "yes" else "片付けていない"
    # どの失敗でも HA には「失敗」を返す（声をかける側に倒す）。ha.py・camera.py は SystemExit で失敗を投げる
    except (Exception, SystemExit) as e:  # noqa: BLE001
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        option = "失敗"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    call("input_select.select_option", [RESULT], {"option": option})
    print(json.dumps({"result": option}, ensure_ascii=False))


if __name__ == "__main__":
    main()
