#!/bin/bash
# core（動いていなければ起動）→ stage をブラウザで開く → ここで claude。
# claude を抜けたら、このスクリプトが起動した core だけ止める。
set -euo pipefail

port=${PORT:-8765}
url=http://127.0.0.1:$port
here=$(dirname "$(realpath "$0")")
log=${XDG_CACHE_HOME:-$HOME/.cache}/saru9000/core-$port.log

up() { curl -sf -o /dev/null "$url/"; }

core=
if up; then
  echo "core: already running at $url"
else
  mkdir -p "$(dirname "$log")"
  "$here/../core/server.py" --host 127.0.0.1 --port "$port" >"$log" 2>&1 &
  core=$!
  trap 'kill "$core" 2>/dev/null; wait "$core" 2>/dev/null || true' EXIT
  echo "core: starting at $url (log: $log)"
  # 初回は uv が依存を入れるので時間がかかる
  for _ in $(seq 120); do
    up && break
    kill -0 "$core" 2>/dev/null || { echo "core exited, see $log" >&2; exit 1; }
    sleep 1
  done
  up || { echo "core did not come up in 120 s, see $log" >&2; exit 1; }
fi

xdg-open "$url/" >/dev/null 2>&1 || echo "open $url/ in a browser"
cd "$here"
CORE_URL=$url claude
