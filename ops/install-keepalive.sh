#!/bin/bash
# Install (or reinstall) the launchd agent that keeps scripts/serve.py running:
# starts it at login, restarts it on crash. Safe to re-run after pulling
# changes — it replaces the agent in place. See docs/remote-access.md.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-$(command -v python3)}"
LABEL="com.jobboard.serve"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PORT="${BOARD_PORT:-8000}"

mkdir -p "$REPO/data/logs" "$HOME/Library/LaunchAgents"

sed -e "s|{{REPO}}|$REPO|g" -e "s|{{PYTHON}}|$PYTHON|g" \
    "$REPO/ops/$LABEL.plist.template" > "$PLIST"

# Unload a previous install of the agent, if any.
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true

# A manually-started server would hold the port and crash-loop the agent;
# hand ownership over to launchd.
EXISTING="$(lsof -ti tcp:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "$EXISTING" ]; then
  echo "Stopping existing listener on port $PORT (pid $EXISTING) — the launchd agent takes over."
  kill "$EXISTING" || true
  sleep 1
fi

launchctl bootstrap "gui/$UID" "$PLIST"

echo "Installed $LABEL"
echo "  plist: $PLIST"
echo "  logs:  $REPO/data/logs/serve.log"
echo "  board: http://127.0.0.1:$PORT"
echo "Manage:  launchctl kickstart -k gui/$UID/$LABEL   # force restart"
echo "         launchctl bootout gui/$UID/$LABEL        # uninstall/stop"
