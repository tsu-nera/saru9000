"""mouse の Waydroid で動く Google Home アプリを操作する（画面を見る・押す）。

Google Home の機器一覧（Online/Offline）・自動化はクラウド経由なので Waydroid から見える。
Cast 機器の設定・再起動など LAN 直結の機能は Waydroid（NAT 内）からは使えない。
画面は 925x1000。座標はスクリーンショットから読む（uiautomator dump は空を返す）。

    python3 home/waydroid.py start          # 起動して Google Home を開く
    python3 home/waydroid.py shot -o <scratchpad>/home.png
    python3 home/waydroid.py tap 424 210
    python3 home/waydroid.py swipe 500 850 500 350
    python3 home/waydroid.py key KEYCODE_BACK
"""

import argparse
import os
import subprocess
import time
from pathlib import Path

HOME_APP = "com.google.android.apps.chromecast.app"


def run(*args: str, timeout: float = 30) -> str:
    # waydroid shell は受け取った stdin/stdout/stderr のファイルを root 所有に変えるので、必ずパイプで渡す
    r = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
    return r.stdout.decode(errors="replace").strip()


def shell(*args: str, timeout: float = 30) -> str:
    return run("sudo", "-n", "waydroid", "shell", "--", *args, timeout=timeout)


def container() -> str:
    for line in run("waydroid", "status").splitlines():
        if line.startswith("Container:"):
            return line.split()[-1]
    return "UNKNOWN"


def booted() -> str:
    try:
        return shell("getprop", "sys.boot_completed", timeout=10)
    except subprocess.TimeoutExpired:
        return ""


def start():
    # 省電力で FROZEN になると shell が返らなくなる。UI を出し、suspend を切る
    if container() in ("FROZEN", "FREEZING"):
        run("sudo", "-n", "systemctl", "restart", "waydroid-container", timeout=60)
    env = {**os.environ, "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY", "wayland-1")}
    subprocess.Popen(["waydroid", "show-full-ui"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, env=env)
    deadline = time.monotonic() + 120
    while booted() != "1":
        if time.monotonic() > deadline:
            raise SystemExit("Waydroid did not boot within 120s")
        time.sleep(5)
    run("waydroid", "prop", "set", "persist.waydroid.suspend", "false")
    shell("monkey", "-p", HOME_APP, "-c", "android.intent.category.LAUNCHER", "1")


def shot(out: Path):
    shell("screencap", "-p", "/data/local/tmp/shot.png")
    r = subprocess.run(["sudo", "-n", "waydroid", "shell", "--", "cat", "/data/local/tmp/shot.png"],
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
    out.write_bytes(r.stdout)
    print(out.resolve())


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("start")
    s = sub.add_parser("shot")
    s.add_argument("-o", "--output", default="waydroid.png")
    s = sub.add_parser("tap")
    s.add_argument("x")
    s.add_argument("y")
    s = sub.add_parser("swipe")
    s.add_argument("coords", nargs=4, metavar=("X1", "Y1", "X2", "Y2"))
    s = sub.add_parser("key")
    s.add_argument("keycode", help="例: KEYCODE_BACK")
    args = p.parse_args()

    if args.command == "start":
        start()
    elif args.command == "shot":
        shot(Path(args.output))
    elif args.command == "tap":
        shell("input", "tap", args.x, args.y)
    elif args.command == "swipe":
        shell("input", "swipe", *args.coords, "400")
    else:
        shell("input", "keyevent", args.keycode)


if __name__ == "__main__":
    main()
