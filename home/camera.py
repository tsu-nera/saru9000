"""部屋のカメラを操作する。C270（go2rtc + HA の Generic Camera）と Tapo C220（PTZ）。

C270 のオン/オフは go2rtc コンテナの起動・停止と、HA の generic config entry の有効・無効を揃えて切り替える
（片方だけだと HA が止まったストリームを叩き続ける）。照明が消えていると snap は真っ黒になる。

    python3 home/camera.py on|off|status
    python3 home/camera.py snap [-o snap.jpg]
    python3 home/camera.py tapo snap [-o OUT] [--lights]
    python3 home/camera.py tapo move left|right|up|down [times] [--speed 1.0]
    python3 home/camera.py tapo sweep [-o OUTDIR] [--lights]
"""

import argparse
import contextlib
import json
import shlex
import subprocess
import tempfile
import time
import urllib.error
from pathlib import Path

from ha import CONFIG, call, rest, secret, ssh, ssh_bytes, state, ws

def generic_entry() -> dict:
    entries = ws("config_entries/get", domain="generic")
    if len(entries) != 1:
        raise SystemExit(f"expected 1 generic entry, got {len(entries)}")
    return entries[0]


def set_entry(disabled_by: str | None):
    ws("config_entries/disable", entry_id=generic_entry()["entry_id"], disabled_by=disabled_by)


def entity_state() -> str | None:
    # entry を無効にすると entity ごと消えて 404 になる
    try:
        return state(CONFIG["camera_entity"])["state"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def status() -> dict:
    entry = generic_entry()
    return {
        "go2rtc": ssh(f"docker inspect -f '{{{{.State.Status}}}}' {CONFIG['go2rtc_container']}"),
        "ha_entry": {"entry_id": entry["entry_id"], "disabled_by": entry["disabled_by"]},
        "entity_state": entity_state(),
    }


# vaio 上で動かす固定スクリプト（秘密を含まない）。user/pass/host を stdin の3行で受ける。
# ffmpeg には RTSP の資格情報だけを渡すオプションが無いので、URL は vaio 上の ffmpeg の argv に
# 実行中だけ載る（ssh の argv やディスクには残らない）。
# TCP にするのは UDP だと映像の下半分が崩れるため。静止画を HA の ONVIF から取らないのも崩れるため。
TAPO_SNAP_SCRIPT = """
import subprocess, sys, urllib.parse
user, password, host = (sys.stdin.readline().rstrip("\\n") for _ in range(3))
q = lambda v: urllib.parse.quote(v, safe="")
url = f"rtsp://{q(user)}:{q(password)}@{host}:554/stream1"
r = subprocess.run(
    ["ffmpeg", "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", url,
     "-frames:v", "1", "-q:v", "2", "-f", "image2", "-vcodec", "mjpeg", "pipe:1"],
    stdout=subprocess.PIPE,
)
sys.stdout.buffer.write(r.stdout)
sys.exit(r.returncode)
"""

SETTLE_AFTER_LIGHTS = 2  # 照明を上げてからカメラの露出が落ち着くまで
SETTLE_AFTER_RESTORE = 4  # apply の後、状態が戻るのを待つ秒数


def snap_tapo() -> bytes:
    """Tapo の静止画（最大解像度の JPEG）を RTSP から1枚取る。ffmpeg は vaio 側で動かす。"""
    stdin = f"{secret('TAPO_CAMERA_USERNAME')}\n{secret('TAPO_CAMERA_PASSWORD')}\n{secret('TAPO_CAMERA_HOST')}\n"
    data = ssh_bytes(f"python3 -c {shlex.quote(TAPO_SNAP_SCRIPT)}", stdin=stdin)
    if not data:
        raise SystemExit("tapo snap: empty image")
    return data


def _brightness(entity_id: str) -> int | None:
    return state(entity_id)["attributes"].get("brightness")


@contextlib.contextmanager
def lights_up():
    """天井の照明を撮影の間だけ 100% にし、抜けたら Adaptive Lighting に戻す。消えていた照明は消す。"""
    lights = CONFIG["ceiling_lights"]
    al = CONFIG["adaptive_lighting_switch"]
    was_off = [e for e in lights if state(e)["state"] == "off"]
    was_on = [e for e in lights if e not in was_off]
    try:
        call("adaptive_lighting.set_manual_control", [], {"entity_id": al, "lights": lights, "manual_control": True})
        call("light.turn_on", lights, {"brightness_pct": 100})
        time.sleep(SETTLE_AFTER_LIGHTS)
        yield
    finally:
        call("adaptive_lighting.set_manual_control", [], {"entity_id": al, "lights": lights, "manual_control": False})
        apply = {"entity_id": al, "lights": lights, "turn_on_lights": False}
        call("adaptive_lighting.apply", [], apply)
        time.sleep(SETTLE_AFTER_RESTORE)
        # apply は1回目で戻らないことがある
        if any(_brightness(e) == 255 for e in was_on):
            call("adaptive_lighting.apply", [], apply)
        if was_off:
            call("light.turn_off", was_off, {})


PTZ_AXES = {
    "left": {"pan": "LEFT"}, "right": {"pan": "RIGHT"},
    "up": {"tilt": "UP"}, "down": {"tilt": "DOWN"},
}


def ptz(direction: str, times: int, speed: float):
    # continuous_duration が 1 秒を超えると HA が 400 を返すので、1 秒の移動を繰り返す
    for _ in range(times):
        call("onvif.ptz", [CONFIG["tapo_camera_entity"]], {
            **PTZ_AXES[direction], "move_mode": "ContinuousMove", "continuous_duration": 1, "speed": speed,
        })


def _drawtext_escape(label: str) -> str:
    """drawtext の text='…'（単引用符の中）に入れるラベルのエスケープ。"""
    return (label.replace("\\", "\\\\").replace(":", "\\:").replace("%", "\\%")
            .replace("'", "'\\''"))


def sheet_filter(labels: list[str], cols: int = 3, width: int = 800) -> str:
    """画像を行優先で並べ、各コマの左上にラベルを入れる ffmpeg の -filter_complex。"""
    n = len(labels)
    chains = [
        f"[{i}:v]scale={width}:-2,drawtext=text='{_drawtext_escape(label)}':x=8:y=8:fontsize=28:"
        f"fontcolor=yellow:box=1:boxcolor=black@0.7[v{i}]"
        for i, label in enumerate(labels)
    ]
    if n == 1:
        return chains[0].rsplit("[v0]", 1)[0]
    layout = "|".join(
        f"{'+'.join(['w0'] * (i % cols)) or '0'}_{'+'.join(['h0'] * (i // cols)) or '0'}" for i in range(n)
    )
    inputs = "".join(f"[v{i}]" for i in range(n))
    return ";".join(chains + [f"{inputs}xstack=inputs={n}:layout={layout}:fill=black"])


def make_sheet(images: list[Path], out: Path):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for img in images:
        cmd += ["-i", str(img)]
    cmd += ["-filter_complex", sheet_filter([img.stem for img in images]), "-frames:v", "1", "-q:v", "3", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"ffmpeg failed: {r.stderr.strip()}")


def tapo_snap(output: str | None, lights: bool) -> dict:
    out = Path(output) if output else Path(tempfile.mkdtemp(prefix="tapo-")) / "snap.jpg"
    with lights_up() if lights else contextlib.nullcontext():
        data = snap_tapo()
    out.write_bytes(data)
    return {"path": str(out.resolve())}


def tapo_sweep(args) -> dict:
    outdir = Path(args.output or tempfile.mkdtemp(prefix="tapo-sweep-"))
    outdir.mkdir(parents=True, exist_ok=True)
    frames = []
    with lights_up() if args.lights else contextlib.nullcontext():
        ptz("down", args.tilt_down, args.speed)
        ptz("left", args.to_left, args.speed)
        for i in range(args.steps):
            time.sleep(args.settle)
            frame = outdir / f"p{i}.jpg"
            frame.write_bytes(snap_tapo())
            frames.append(frame)
            if i < args.steps - 1:
                ptz("right", args.pan_per_step, args.speed)
    sheet = outdir / "sheet.jpg"
    make_sheet(frames, sheet)
    return {"sheet": str(sheet.resolve()), "frames": [str(f.resolve()) for f in frames]}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("on", help="C270 を起動")
    sub.add_parser("off", help="C270 を停止")
    sub.add_parser("status", help="C270 の状態")
    s = sub.add_parser("snap", help="C270 の静止画")
    s.add_argument("-o", "--output", default="snap.jpg", help="snap の保存先")

    tapo = sub.add_parser("tapo", help="Tapo C220（PTZ）の操作")
    tsub = tapo.add_subparsers(dest="tapo_command", required=True)
    lights_help = "撮影の間だけ天井の照明を 100%% にする（終わったら Adaptive Lighting に戻す）"
    s = tsub.add_parser("snap", help="静止画を1枚（RTSP stream1、最大解像度）")
    s.add_argument("-o", "--output", help="保存先（省略時は一時ディレクトリの snap.jpg）")
    s.add_argument("--lights", action="store_true", help=lights_help)
    s = tsub.add_parser("move", help="首振り（1 秒の移動を times 回）")
    s.add_argument("direction", choices=list(PTZ_AXES))
    s.add_argument("times", nargs="?", type=int, default=1)
    s.add_argument("--speed", type=float, default=1.0)
    s = tsub.add_parser("sweep", help="下向き→左端から右へ一定間隔で撮り、一覧画像 sheet.jpg を作る")
    s.add_argument("-o", "--output", help="出力ディレクトリ（省略時は一時ディレクトリ）")
    s.add_argument("--steps", type=int, default=6, help="撮る枚数")
    s.add_argument("--pan-per-step", type=int, default=2, help="1 枚ごとに右へ振る回数")
    s.add_argument("--tilt-down", type=int, default=3, help="最初に下へ向ける回数（下向きの限界は設置位置で変わる）")
    s.add_argument("--to-left", type=int, default=10, help="撮り始める前に左へ振る回数（左端までの回数は設置位置で変わる）")
    s.add_argument("--settle", type=float, default=2, help="動かした後の待ち秒数")
    s.add_argument("--speed", type=float, default=1.0)
    s.add_argument("--lights", action="store_true", help=lights_help)
    return p


def main():
    args = build_parser().parse_args()

    if args.command == "tapo":
        if args.tapo_command == "snap":
            out = tapo_snap(args.output, args.lights)
        elif args.tapo_command == "move":
            ptz(args.direction, args.times, args.speed)
            out = {"direction": args.direction, "times": args.times, "speed": args.speed}
        else:
            out = tapo_sweep(args)
        print(json.dumps(out, ensure_ascii=False))
        return
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
