#!/usr/bin/env bash
#
# runner-doctor.sh - check & repair the GitHub Actions runner on the OTHER Mac.
# SAFE: never kills processes, never runs sudo. Prints the sudo commands for YOU to run.
#
#   bash scripts/runner-doctor.sh                  # check + fix what is safe
#   bash scripts/runner-doctor.sh --install-keepalive   # + 10-min watchdog and no-sleep agent (launchd)
#   bash scripts/runner-doctor.sh --quiet          # (used by the watchdog) only act, little output
#
# If the runner folder/registration is missing it tells you to run: bash fix-runner.sh
set -uo pipefail

REPO="BOBRIKH75/job-finder"
RUNNER_DIR="${RUNNER_DIR:-$HOME/gh-runner}"
BREW_PATHS="/usr/local/homebrew/bin:/opt/homebrew/bin:/usr/local/bin"
QUIET=0; KEEPALIVE=0
for a in "$@"; do case "$a" in --quiet) QUIET=1;; --install-keepalive) KEEPALIVE=1;; esac; done
FAILS=0
say(){  [ "$QUIET" = 1 ] || printf '%s\n' "$*"; }
ok(){   say "  OK    $*"; }
warn(){ say "  WARN  $*"; }
bad(){  printf '  FAIL  %s\n' "$*"; FAILS=$((FAILS+1)); }

[ "$(uname -s)" = "Darwin" ] || { echo "Run this on the runner Mac."; exit 1; }
export PATH="$BREW_PATHS:$PATH"
say "== runner-doctor ($(date '+%F %T')) =="

# 1. runner folder
if [ -f "$RUNNER_DIR/config.sh" ] && [ -f "$RUNNER_DIR/.runner" ]; then
  ok "runner folder $RUNNER_DIR is configured"
else
  bad "no configured runner in $RUNNER_DIR  ->  run:  cd <job-finder repo> && git pull && bash fix-runner.sh"
  exit 1
fi

# 2. .path file (the runner reads this for PATH - without it jobs cannot find python3/brew tools)
want="$BREW_PATHS:/usr/bin:/bin:/usr/sbin:/sbin"
if [ "$(cat "$RUNNER_DIR/.path" 2>/dev/null)" = "$want" ]; then
  ok ".path has Homebrew paths"
else
  printf '%s' "$want" > "$RUNNER_DIR/.path" && ok ".path written (restart of runner service needed to take effect)" && PATH_CHANGED=1
fi

# 3. launchd service (installed + loaded + running)
PLIST_GLOB="$HOME/Library/LaunchAgents/actions.runner.*.plist"
if ls $PLIST_GLOB >/dev/null 2>&1; then
  ok "launchd plist present"
else
  warn "service not installed - installing"
  ( cd "$RUNNER_DIR" && ./svc.sh install >/dev/null 2>&1 && ./svc.sh start >/dev/null 2>&1 ) && ok "service installed + started" || bad "svc.sh install failed -> run: bash fix-runner.sh"
fi
LABEL="$(launchctl list 2>/dev/null | awk '/actions\.runner\./{print $3}' | head -1)"
if [ -n "$LABEL" ] && pgrep -f "Runner.Listener" >/dev/null 2>&1; then
  ok "runner process is running ($LABEL)"
  if [ "${PATH_CHANGED:-0}" = 1 ]; then
    say "  ...applying new .path via launchctl kickstart (restarts the service, not a kill -9)"
    launchctl kickstart -k "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || warn "kickstart failed; run: cd $RUNNER_DIR && ./svc.sh stop && ./svc.sh start"
  fi
else
  warn "runner not running - starting service"
  ( cd "$RUNNER_DIR" && ./svc.sh start >/dev/null 2>&1 )
  [ -n "$LABEL" ] && launchctl kickstart "gui/$(id -u)/$LABEL" >/dev/null 2>&1
  sleep 4
  pgrep -f "Runner.Listener" >/dev/null 2>&1 && ok "runner started" || bad "runner would not start -> run: bash fix-runner.sh"
fi

# 4. Python >= 3.10
PY=""
for p in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)'; then PY="$p"; break; fi
done
[ -n "$PY" ] && ok "Python OK: $PY ($($PY --version 2>&1))" || bad "no Python >= 3.10. Fix:  brew install python@3.12"

# 5. Chrome
if [ -d "/Applications/Google Chrome.app" ]; then ok "Google Chrome installed"; else bad "Chrome missing. Fix: brew install --cask google-chrome"; fi

# 6. git + gh
command -v git >/dev/null 2>&1 && ok "git present" || bad "git missing (xcode-select --install)"
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  ok "gh logged in"
  st="$(gh api "repos/$REPO/actions/runners" --jq '.runners[]|.name+" "+.status' 2>/dev/null | tr '\n' ';')"
  [ -n "$st" ] && say "  INFO  GitHub sees runners: $st"
else
  warn "gh not logged in (optional here): brew install gh && gh auth login"
fi

# 7. sleep settings (print only - needs sudo, you run it)
sleepmin="$(pmset -g 2>/dev/null | awk '/^ *sleep /{print $2}')"
if [ "${sleepmin:-1}" = "0" ]; then ok "system sleep is disabled"; else
  warn "Mac can sleep (sleep=${sleepmin:-?} min) -> runner goes offline. Run these YOURSELF in Terminal:"
  say "        sudo pmset -a sleep 0 disablesleep 1 displaysleep 30 powernap 0"
  say "        (Lid closed? Keep it plugged in, or use: Settings > Battery > Options > 'Prevent automatic sleeping on power adapter')"
fi

# 8. keepalive (watchdog every 10 min + caffeinate), only with --install-keepalive
if [ "$KEEPALIVE" = 1 ]; then
  DOC="$(cd "$(dirname "$0")" && pwd)/runner-doctor.sh"
  LA="$HOME/Library/LaunchAgents"; mkdir -p "$LA"
  cat > "$LA/com.jobfinder.runner-watchdog.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>Label</key><string>com.jobfinder.runner-watchdog</string>
<key>ProgramArguments</key><array><string>/bin/bash</string><string>$DOC</string><string>--quiet</string></array>
<key>StartInterval</key><integer>600</integer><key>RunAtLoad</key><true/>
<key>StandardOutPath</key><string>$HOME/runner-watchdog.log</string><key>StandardErrorPath</key><string>$HOME/runner-watchdog.log</string></dict></plist>
PL
  cat > "$LA/com.jobfinder.caffeinate.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>Label</key><string>com.jobfinder.caffeinate</string>
<key>ProgramArguments</key><array><string>/usr/bin/caffeinate</string><string>-i</string><string>-s</string><string>-m</string></array>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/></dict></plist>
PL
  for n in runner-watchdog caffeinate; do
    launchctl bootout "gui/$(id -u)/com.jobfinder.$n" >/dev/null 2>&1
    launchctl bootstrap "gui/$(id -u)" "$LA/com.jobfinder.$n.plist" >/dev/null 2>&1 && ok "keepalive agent com.jobfinder.$n loaded" || warn "could not load $n agent"
  done
fi

say ""
if [ "$FAILS" = 0 ]; then say "RESULT: all good."; exit 0; else echo "RESULT: $FAILS problem(s) above."; exit 1; fi
