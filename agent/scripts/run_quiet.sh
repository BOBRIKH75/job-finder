#!/usr/bin/env bash
# Run a bot without getting in the way of the person using this laptop.
#   - Pause switch:  touch ~/.cv-bots-pause   (resume: rm ~/.cv-bots-pause)
#   - macOS: taskpolicy -c utility = lower CPU/IO priority, prefers efficiency cores.
#   - Elsewhere: nice only.
set -uo pipefail
if [ -f "$HOME/.cv-bots-pause" ]; then
  echo "::notice::bots paused (~/.cv-bots-pause exists) - skipping $*"
  exit 0
fi
export CV_QUIET_WINDOW="${CV_QUIET_WINDOW:-1}"
if command -v taskpolicy >/dev/null 2>&1; then
  exec taskpolicy -c utility nice -n 10 "$@"
fi
exec nice -n 10 "$@"
