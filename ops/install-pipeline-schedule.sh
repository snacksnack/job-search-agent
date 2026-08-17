#!/bin/bash
# Install (or reinstall) the launchd agent that runs scripts/pipeline.py every
# morning at 07:00, independent of any Claude session. Safe to re-run after
# pulling changes — it replaces the agent in place. See README.md → "Fully
# hands-off (launchd)".
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-$(command -v python3)}"
LABEL="com.jobboard.pipeline"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$REPO/data/logs" "$HOME/Library/LaunchAgents"

sed -e "s|{{REPO}}|$REPO|g" -e "s|{{PYTHON}}|$PYTHON|g" \
    "$REPO/ops/$LABEL.plist.template" > "$PLIST"

# Unload a previous install of the agent, if any.
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST"

# The agent runs through a login zsh so ~/.zshenv supplies the Adzuna keys;
# warn now if a login shell wouldn't see them.
if ! /bin/zsh -lc '[ -n "${ADZUNA_APP_ID:-}" ] && [ -n "${ADZUNA_APP_KEY:-}" ]'; then
  echo "WARNING: ADZUNA_APP_ID/ADZUNA_APP_KEY are not visible in a login shell," >&2
  echo "         so the Adzuna source will be skipped. Export them in ~/.zshenv." >&2
fi

echo "Installed $LABEL — runs pipeline.py daily at 07:00 (fires at next wake if asleep)."
echo "  plist: $PLIST"
echo "  logs:  $REPO/data/logs/pipeline.log"
echo "Manage:  launchctl kickstart gui/$UID/$LABEL   # run once now"
echo "         launchctl bootout gui/$UID/$LABEL     # uninstall"
