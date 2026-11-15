#!/usr/bin/env bash
# Kill ONLY leftover automation browsers (Playwright/patchright/selenium) on the self-hosted runner.
# Never touches your personal Chrome or the Chrome DevTools MCP browser: it matches only
# automation-specific profile dirs (and chromedriver), never generic flags.
# Safe to run at job start (clears orphans from a cancelled/timed-out run) and at job end.
set -u
PATTERNS=(
  'user-data-dir=.*playwright_chromiumdev_profile'  # Playwright temp profiles
  'user-data-dir=.*patchright'                      # patchright temp profiles
  'chromedriver'                     # selenium / undetected-chromedriver
  'user-data-dir=.*\.dice-profile'   # Dice persistent profile
  'user-data-dir=.*\.cv-indeed-profile'
  'user-data-dir=.*linkedin.*profile'
  'user-data-dir=.*undetected_chromedriver'
)
count_before=0
for p in "${PATTERNS[@]}"; do
  n=$(pgrep -f -- "$p" 2>/dev/null | wc -l | tr -d ' ')
  count_before=$((count_before + n))
  pkill -TERM -f -- "$p" 2>/dev/null || true
done
if [ "$count_before" -gt 0 ]; then
  sleep 3
  for p in "${PATTERNS[@]}"; do pkill -KILL -f -- "$p" 2>/dev/null || true; done
fi
echo "kill-automation-chrome: cleaned ${count_before} leftover automation process(es)"
exit 0
