"""家の音を出す・聞く。vaio のスピーカーで話しかけ、vaio のマイクで録って文字起こしする（声の往復試験）。

say: VOICEVOX で合成して pw-play、並行して pw-record で録音し、core の listen.py（ReazonSpeech）で
文字に起こす。--expect を付けると、その entity（script.* なら last_triggered、それ以外は state）が
変わったかも判定する。試験中だけ vaio の出力音量を --volume に上げ、終わったら元に戻す。
listen: vaio のマイクを ssh 越しに mouse の既定の出力（ヘッドホン）へ生で流す。人が耳で確かめる用。
文字起こしの前には小さい音を持ち上げる（Google スピーカーの返事は 2m 先でも録音上かなり小さい）。

    python3 home/voice.py say "OK Google、、、ただいま" --expect script.tadaima
    python3 home/voice.py listen --seconds 40 -o <scratchpad>/home.wav   # 別端末で流しながら say する
    python3 home/voice.py transcribe <scratchpad>/home.wav
"""

import argparse
import json
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from ha import CONFIG, on_host, ssh, state

# 小さい音（遠くのスピーカーの返事）を持ち上げる。文字起こし用（遅延が大きいので生で聞く用には使わない）
BOOST = "dynaudnorm=f=150:g=15:m=30"

# vaio で走らせる。stdout の最後の1行が JSON。
REMOTE = r"""
set -eu
D=$(mktemp -d)
OLD=$(wpctl get-volume @DEFAULT_AUDIO_SINK@ | awk '{print $2}')
trap 'wpctl set-volume @DEFAULT_AUDIO_SINK@ "$OLD"; rm -rf "$D"' EXIT
Q=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "$TEXT")
curl -sf -X POST "$VOICEVOX/audio_query?speaker=$SPEAKER&text=$Q" -o "$D/query.json"
curl -sf -X POST -H 'Content-Type: application/json' "$VOICEVOX/synthesis?speaker=$SPEAKER" \
  --data-binary @"$D/query.json" -o "$D/say.wav"
wpctl set-volume @DEFAULT_AUDIO_SINK@ "$VOLUME"
timeout "$SECONDS_" pw-record --rate 16000 --channels 1 --format s16 "$D/rec.wav" &
REC=$!
sleep 0.5
PLAYED=$(date +%T)
pw-play "$D/say.wav"
wait $REC || true
ffmpeg -loglevel error -y -i "$D/rec.wav" -af "$BOOST" -ar 16000 -ac 1 -sample_fmt s16 "$D/rec_b.wav"
cd "$REPO/agent/core"
./listen.py "$D/rec_b.wav" 2>/dev/null | python3 -c '
import json, sys
print(json.dumps({"played_at": sys.argv[1], "transcript": sys.stdin.read().split()}, ensure_ascii=False))
' "$PLAYED"
"""


def marker(entity_id: str) -> str:
    s = state(entity_id)
    if entity_id.startswith("script."):
        return s["attributes"].get("last_triggered") or ""
    return s["state"]


def exports(env: dict) -> str:
    env = {**env, "BOOST": BOOST, "REPO": CONFIG["vaio_repo"].replace("~", "$HOME")}
    return "".join(f'export {k}="{v}"\n' if k == "REPO" else f"export {k}={shlex.quote(str(v))}\n"
                   for k, v in env.items())


def say(text: str, speaker: int, seconds: int, volume: float) -> dict:
    env = {"TEXT": text, "SPEAKER": speaker, "SECONDS_": seconds, "VOLUME": volume,
           "VOICEVOX": CONFIG["voicevox_url_on_vaio"]}
    return json.loads(ssh("bash -s", stdin=exports(env) + REMOTE).splitlines()[-1])


def listen(seconds: int, gain: int, out: Path | None):
    """vaio のマイク → ssh → (+gain dB, リミッター) → mouse の pw-play。out があれば素の録音も wav で残す。"""
    rec = subprocess.Popen(["ssh", CONFIG["ssh_host"],
                            f"timeout {seconds} pw-record --rate 16000 --channels 1 --format s16 --raw -"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
    amp = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", "-",
                            "-af", f"volume={gain}dB,alimiter=limit=0.5", "-f", "s16le", "-"],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    play = subprocess.Popen(["pw-play", "--raw", "--rate", "16000", "--channels", "1", "--format", "s16", "-"],
                            stdin=amp.stdout)
    raw = bytearray()
    while chunk := rec.stdout.read(3200):
        raw += chunk
        amp.stdin.write(chunk)
        amp.stdin.flush()
    amp.stdin.close()
    play.wait()
    if out:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", "-",
                        str(out)], input=bytes(raw), check=True)
        print(out.resolve())


def transcribe(wav: Path) -> list[str]:
    remote = f"/tmp/voice_transcribe_{wav.name}"
    if on_host():
        shutil.copyfile(wav, remote)
    else:
        subprocess.run(["scp", "-q", str(wav), f"{CONFIG['ssh_host']}:{remote}"], check=True)
    script = exports({"IN": remote}) + r"""
set -eu
D=$(mktemp -d)
trap 'rm -rf "$D" "$IN"' EXIT
ffmpeg -loglevel error -y -i "$IN" -af "$BOOST" -ar 16000 -ac 1 -sample_fmt s16 "$D/b.wav"
cd "$REPO/agent/core"
./listen.py "$D/b.wav" 2>/dev/null
"""
    return ssh("bash -s", stdin=script).split()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("say", help="話しかけて録音・文字起こし")
    s.add_argument("text", help="読ませる文。呼びかけの後は「、、、」で間を空ける")
    s.add_argument("--speaker", type=int, default=2, help="VOICEVOX の話者 ID（Google が反応したのは 2）")
    s.add_argument("--seconds", type=int, default=14, help="録音秒数（再生開始の 0.5 秒前から）")
    s.add_argument("--volume", type=float, default=1.0, help="試験中の vaio 出力音量")
    s.add_argument("--expect", help="変化を待つ entity（例: script.tadaima）")
    s.add_argument("--wait", type=int, default=10, help="--expect の変化を録音後に待つ秒数")
    s = sub.add_parser("listen", help="vaio のマイクを mouse のヘッドホンで生で聞く")
    s.add_argument("--seconds", type=int, default=40)
    s.add_argument("--gain", type=int, default=20, help="持ち上げる dB（リミッターで割れは抑える）")
    s.add_argument("-o", "--output", type=Path, help="素の録音を wav で残す（transcribe に渡せる）")
    s = sub.add_parser("transcribe", help="wav を小さい音を持ち上げてから文字起こし")
    s.add_argument("wav", type=Path)
    args = p.parse_args()

    if args.command == "listen":
        listen(args.seconds, args.gain, args.output)
        return
    if args.command == "transcribe":
        print(json.dumps(transcribe(args.wav), ensure_ascii=False))
        return

    before = marker(args.expect) if args.expect else None
    out = say(args.text, args.speaker, args.seconds, args.volume)
    if args.expect:
        deadline = time.monotonic() + args.wait
        while (after := marker(args.expect)) == before and time.monotonic() < deadline:
            time.sleep(1)
        out["expect"] = {"entity_id": args.expect, "before": before, "after": after, "changed": after != before}
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
