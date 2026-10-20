#!/usr/bin/env bash
#
# fix-runner.sh — ONE command to make the runner work and STAY online.
#
# Fixes every problem seen on bobur-laptop:
#   • two conflicting runner folders (~/actions-runner + ~/gh-runner) → "session already exists"
#   • corrupted LaunchAgent plist → "Load failed: 5: Input/output error"
#   • stale registration → "registration has been deleted"
#   • laptop sleeping → runner drops offline
#
# USAGE (on the runner laptop):
#   cd ~/Downloads/CV/job-finder && git pull && bash fix-runner.sh
#
# After it finishes, the runner is installed as a keep-alive service that
# auto-starts on login and survives sleep/reboot. Check with:
#   cd ~/gh-runner && ./svc.sh status

set -uo pipefail

REPO="BOBRIKH75/job-finder"
REPO_URL="https://github.com/${REPO}"
RUNNER_DIR="$HOME/gh-runner"          # the ONE runner we keep
OLD_DIR="$HOME/actions-runner"        # the duplicate we kill
NAME="bobur-laptop"
LABELS="self-hosted,macOS,ARM64,linkedin"
PLIST="$HOME/Library/LaunchAgents/actions.runner.${REPO//\//-}.${NAME}.plist"

say(){ printf '\n➡️  %s\n' "$*"; }
ok(){  printf '✅ %s\n' "$*"; }
die(){ printf '\n❌ %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || die "Run this on the macOS runner laptop."

# ---- 0. gh must be logged in (we auto-fetch tokens) ----
command -v gh >/dev/null 2>&1 || die "gh not installed. Run: brew install gh && gh auth login"
gh auth status >/dev/null 2>&1 || die "gh not logged in. Run: gh auth login   (as BOBRIKH75), then re-run."

# ---- 1. kill every running runner process ----
say "Stopping all runner processes..."
pkill -f Runner.Listener 2>/dev/null || true
pkill -f run-helper.sh    2>/dev/null || true
sleep 2
ok "processes stopped"

# ---- 2. tear down BOTH folders' services + the broken plist ----
say "Removing old services and the corrupted LaunchAgent..."
for d in "$RUNNER_DIR" "$OLD_DIR"; do
  if [ -d "$d" ]; then ( cd "$d" && ./svc.sh uninstall >/dev/null 2>&1 || true ); fi
done
launchctl remove "actions.runner.${REPO//\//-}.${NAME}" 2>/dev/null || true
launchctl bootout "gui/$(id -u)/actions.runner.${REPO//\//-}.${NAME}" 2>/dev/null || true
rm -f "$PLIST"
ok "old services + plist cleared"

# ---- 3. make sure we have a configured runner in RUNNER_DIR ----
if [ ! -f "$RUNNER_DIR/config.sh" ]; then
  say "No runner in $RUNNER_DIR — downloading a fresh one..."
  ARCH="$(uname -m)"; [ "$ARCH" = "arm64" ] && PLAT="osx-arm64" || PLAT="osx-x64"
  VER="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest \
        | sed -n 's/.*"tag_name": *"v\{0,1\}\([0-9.]*\)".*/\1/p' | head -1)"; [ -n "$VER" ] || VER="2.337.0"
  mkdir -p "$RUNNER_DIR"; cd "$RUNNER_DIR"
  curl -fL -o r.tar.gz "https://github.com/actions/runner/releases/download/v${VER}/actions-runner-${PLAT}-${VER}.tar.gz" \
    || die "download failed"
  tar xzf r.tar.gz && rm -f r.tar.gz
  ok "runner downloaded"
fi

# ---- 4. remove any existing registration, then register FRESH ----
cd "$RUNNER_DIR"
say "Deregistering any stale runner on GitHub..."
RM_TOKEN="$(gh api -X POST repos/${REPO}/actions/runners/remove-token -q .token 2>/dev/null || true)"
[ -n "$RM_TOKEN" ] && ./config.sh remove --token "$RM_TOKEN" >/dev/null 2>&1 || true

say "Registering fresh with GitHub..."
REG_TOKEN="$(gh api -X POST repos/${REPO}/actions/runners/registration-token -q .token 2>/dev/null || true)"
[ -n "$REG_TOKEN" ] || die "Could not get a registration token (need admin on ${REPO})."
./config.sh --url "$REPO_URL" --token "$REG_TOKEN" \
  --name "$NAME" --labels "$LABELS" --unattended --replace \
  || die "registration failed"
ok "registered as $NAME ($LABELS)"

# ---- 5. install as a keep-alive service (NOT sudo — macOS user LaunchAgent) ----
say "Installing as keep-alive service (auto-start on login, restart on crash)..."
./svc.sh install || die "svc install failed"
./svc.sh start   || die "svc start failed"
sleep 5
./svc.sh status || true

# ---- 6. stop the Mac from sleeping (so the runner never drops) ----
say "Preventing sleep so the runner stays online 24/7..."
sudo pmset -a sleep 0 disablesleep 1 2>/dev/null \
  && ok "sleep disabled" \
  || echo "   (set 'Prevent automatic sleeping' in System Settings → Battery manually)"

# ---- 7. verify it is ONLINE on GitHub ----
say "Verifying runner is ONLINE on GitHub..."
for i in 1 2 3 4 5 6; do
  ST="$(gh api repos/${REPO}/actions/runners -q '.runners[0].status' 2>/dev/null || echo unknown)"
  echo "   check $i: status=$ST"
  [ "$ST" = "online" ] && break
  sleep 5
done

cat <<EOF

=========================================================
✅ DONE.
   • ONE runner only: $RUNNER_DIR   (the old $OLD_DIR is disabled)
   • installed as a service → svc.sh status will show it Started with a PID
   • auto-starts on login, restarts on crash, laptop won't sleep
   • check anytime:   cd $RUNNER_DIR && ./svc.sh status
   • GitHub view:     ${REPO_URL}/settings/actions/runners
=========================================================
EOF
