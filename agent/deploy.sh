#!/usr/bin/env bash
# Puts the checkout into service on the home host: builds the stage and
# recreates core's unit when agent/core differs from what it was started from.
#
#   agent/deploy.sh          from another machine: copies the stage's
#                            uncommitted assets, then the host pulls origin/main
#                            (nothing is pushed) and runs --here
#   agent/deploy.sh --here   on the host itself: deploys its working tree as is
#
# DEPLOY_HOST (ssh name, default vaio). FORCE_CORE=1 recreates core anyway.
# Reload the stage tab afterwards: a rebuilt stage reconnects its WebSocket
# but keeps running the old page.
set -euo pipefail

cd "$(dirname "$0")/.."

deploy_here() {
  local state=.git/saru-core-deployed # the commit core was last started from
  git log --oneline -1

  (cd agent/web && npm ci --no-audit --no-fund --loglevel=error && npm run build --silent | tail -n 1)

  # Uncommitted edits under agent/core count as a change too.
  if [ "${FORCE_CORE:-}" ] || [ ! -f "$state" ] ||
    ! git diff --quiet "$(cat "$state")" -- agent/core; then
    # A transient unit: stop + reset-failed, then the same systemd-run.
    systemctl --user stop saru-core 2>/dev/null || true
    systemctl --user reset-failed saru-core 2>/dev/null || true
    systemd-run --user --unit=saru-core --working-directory="$PWD" \
      --setenv=PATH="$HOME/.local/bin:/usr/bin:/bin" \
      uv run --script ./agent/core/server.py --listen --host 127.0.0.1 --host "$(tailscale ip -4)"
    git rev-parse HEAD >"$state"
  fi

  for _ in $(seq 30); do
    if curl -sf -o /dev/null http://127.0.0.1:8765/; then
      echo "core: $(systemctl --user is-active saru-core), stage served"
      return 0
    fi
    sleep 1
  done
  echo "core does not answer on :8765; journalctl --user -u saru-core" >&2
  return 1
}

if [ "${1:-}" = --here ]; then
  deploy_here
  exit
fi

host=${DEPLOY_HOST:-vaio}
git fetch -q origin main
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
  echo "warning: HEAD is not origin/main; the host deploys origin/main" >&2
fi
# The model, motions, music and stage set are third-party and never committed.
# stage.local.json is per machine.
rsync -a --exclude stage.json --exclude stage.local.json --exclude .gitkeep \
  agent/web/public/ "$host:repo/saru9000/agent/web/public/"
# Pull before running the script, so the host runs the new one.
ssh "$host" "cd repo/saru9000 && git pull --ff-only -q && FORCE_CORE='${FORCE_CORE:-}' agent/deploy.sh --here"
