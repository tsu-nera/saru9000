#!/usr/bin/env bash
# 起床の判定（bed_check.py）を vaio ホストで裏で走らせてすぐ返る。
#
# HA の shell_command.bed_check が ssh で呼ぶ。HA 専用鍵は authorized_keys の command= でこのスクリプトに
# 固定してあり、要求された操作は SSH_ORIGINAL_COMMAND に入る（手で動かす時は第1引数）。run 以外は拒否する。
# shell_command は 60 秒で打ち切られ、判定（待ち 15 秒＋claude）はそれを超えうるので待たない。
# 結果は bed_check.py が HA の input_select.ohayo_bed に書く。
#
#     home/bed_check.sh run
set -euo pipefail

action="${SSH_ORIGINAL_COMMAND-${1-}}"
if [[ "$action" != run ]]; then
  echo "usage: bed_check.sh run" >&2
  exit 2
fi

log_dir="$HOME/.local/state/saru9000"
mkdir -p "$log_dir"
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
setsid nohup python3 bed_check.py >>"$log_dir/bed_check.log" 2>&1 </dev/null &
echo started
