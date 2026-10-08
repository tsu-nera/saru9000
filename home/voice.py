"""vaio のスピーカーで話しかけ、同時に vaio のマイクで録音して文字起こしする（声の往復試験）。

VOICEVOX で合成して pw-play、並行して pw-record で録音し、saru-core の listen.py（ReazonSpeech）で
文字に起こす。--expect を付けると、その entity（script.* なら last_triggered、それ以外は state）が
変わったかも判定する。試験中だけ vaio の出力音量を --volume に上げ、終わったら元に戻す。

    python3 home/voice.py say "ねえグーグル、、、ただいまをオンにして" --expect script.tadaima
    python3 home/voice.py say "ねえグーグル、、、今何時" --seconds 12
"""

import argparse
import json
import shlex
import time

from ha import CONFIG, ssh, state

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
cd "$REPO/agent/core"
./listen.py "$D/rec.wav" 2>/dev/null | python3 -c '
import json, sys
print(json.dumps({"played_at": sys.argv[1], "transcript": sys.stdin.read().split()}, ensure_ascii=False))
' "$PLAYED"
"""


def marker(entity_id: str) -> str:
    s = state(entity_id)
    if entity_id.startswith("script."):
        return s["attributes"].get("last_triggered") or ""
    return s["state"]


def say(text: str, speaker: int, seconds: int, volume: float) -> dict:
    env = {"TEXT": text, "SPEAKER": speaker, "SECONDS_": seconds, "VOLUME": volume,
           "VOICEVOX": CONFIG["voicevox_url_on_vaio"], "REPO": CONFIG["vaio_repo"].replace("~", "$HOME")}
    exports = "".join(f'export {k}="{v}"\n' if k == "REPO" else f"export {k}={shlex.quote(str(v))}\n"
                      for k, v in env.items())
    return json.loads(ssh("bash -s", stdin=exports + REMOTE).splitlines()[-1])


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
    args = p.parse_args()

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
