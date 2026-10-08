#!/usr/bin/env bash
# vaio の居室モニター（niri の出力）を点ける・消す。vaio ホストでユーザー tsu-nera として動く。
#
# HA の command_line switch が ssh で呼ぶ。HA 専用鍵は authorized_keys の command= でこのスクリプトに
# 固定してあり、要求された操作は SSH_ORIGINAL_COMMAND に入る（手で動かす時は第1引数）。on / off 以外は拒否する。
# 状態はここでは返さない。HA が /sys/class/drm/card1-HDMI-A-1/dpms を直接読む。
#
#     home/monitor/dpms.sh on|off
set -euo pipefail

action="${SSH_ORIGINAL_COMMAND-${1-}}"

case "$action" in
  on) cmd=power-on-monitors ;;
  off) cmd=power-off-monitors ;;
  *)
    echo "usage: dpms.sh on|off" >&2
    exit 2
    ;;
esac

if [ -z "${NIRI_SOCKET:-}" ]; then
  shopt -s nullglob
  socks=(/run/user/"$(id -u)"/niri.*.sock)
  if [ "${#socks[@]}" -ne 1 ]; then
    echo "niri socket not found or ambiguous (${#socks[@]} matches)" >&2
    exit 1
  fi
  export NIRI_SOCKET="${socks[0]}"
fi

exec niri msg action "$cmd"
