#!/usr/bin/env bash
#
# setup-runner.sh — one-command GitHub Actions self-hosted runner setup for job-finder.
#
# WHY THIS EXISTS:
#   The runner used to live INSIDE the repo folder, so every `git pull` wiped its
#   config (.runner / .credentials) and the runner died ("Not configured").
#   This script installs the runner in a SEPARATE folder (~/gh-runner) that git
#   never touches, registers it with the labels the workflows need, installs it as
#   a background service (survives reboot/sleep/close), and disables Mac sleep.
#
# USAGE (on the runner laptop):
#   1. Get a fresh token (expires ~1 hour):
#        https://github.com/BOBRIKH75/job-finder/settings/actions/runners/new
#      Copy the long token that starts with "A...".
#   2. Run:
#        bash setup-runner.sh <TOKEN>
#
#   To RE-RUN later (re-register after it dies), just run it again with a fresh token.
#
set -euo pipefail

# ---- config ----
REPO_URL="https://github.com/BOBRIKH75/job-finder"
RUNNER_DIR="$HOME/gh-runner"          # SEPARATE from the repo — git pull can't touch it
RUNNER_NAME="bobur-laptop"
RUNNER_LABELS="self-hosted,macOS,linkedin"   # Indeed/Dice need self-hosted; LinkedIn needs all 3
RUNNER_VERSION="2.337.0"              # update if GitHub requires newer

# ---- 1. token ----
TOKEN="${1:-}"
if [ -z "$TOKEN" ]; then
  echo "❌ No token given."
  echo "   Get one here (expires ~1 hour):"
  echo "   ${REPO_URL}/settings/actions/runners/new"
  echo "   Then run:  bash setup-runner.sh <TOKEN>"
  exit 1
fi

# ---- 2. detect Mac architecture ----
ARCH="$(uname -m)"
if [ "$ARCH" = "arm64" ]; then
  PKG="actions-runner-osx-arm64-${RUNNER_VERSION}.tar.gz"
else
  PKG="actions-runner-osx-x64-${RUNNER_VERSION}.tar.gz"
fi
echo "➡️  Mac arch: $ARCH  → package: $PKG"

# ---- 3. stop/remove any OLD runner (incl. one inside the repo) ----
echo "➡️  Cleaning up any existing runner service..."
if [ -d "$RUNNER_DIR" ]; then
  ( cd "$RUNNER_DIR" && sudo ./svc.sh stop 2>/dev/null || true )
  ( cd "$RUNNER_DIR" && sudo ./svc.sh uninstall 2>/dev/null || true )
  ( cd "$RUNNER_DIR" && ./config.sh remove --token "$TOKEN" 2>/dev/null || true )
fi
# kill any stray foreground runner processes
pkill -f Runner.Listener 2>/dev/null || true

# ---- 4. fresh install in the SEPARATE folder ----
echo "➡️  Installing runner in: $RUNNER_DIR  (separate from repo — git-safe)"
rm -rf "$RUNNER_DIR"
mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"

echo "➡️  Downloading runner v${RUNNER_VERSION}..."
curl -fsSL -o actions-runner.tar.gz \
  "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${PKG}"
tar xzf actions-runner.tar.gz
rm -f actions-runner.tar.gz

# ---- 5. register ----
echo "➡️  Registering runner with GitHub..."
./config.sh \
  --url "$REPO_URL" \
  --token "$TOKEN" \
  --labels "$RUNNER_LABELS" \
  --name "$RUNNER_NAME" \
  --unattended --replace

# ---- 6. install as a background service (auto-restart on reboot/sleep/crash) ----
echo "➡️  Installing as a background service..."
sudo ./svc.sh install
sudo ./svc.sh start
sleep 4
sudo ./svc.sh status || true

# ---- 7. stop the Mac from sleeping (keeps the 24/7 runner alive) ----
echo "➡️  Disabling sleep so the runner stays online..."
sudo pmset -a sleep 0 disablesleep 1 2>/dev/null || \
  echo "   (couldn't change pmset — set 'never sleep' manually in System Settings → Battery)"

echo ""
echo "✅ DONE. Runner '$RUNNER_NAME' is installed in $RUNNER_DIR and running as a service."
echo "   - It survives reboot, sleep, closing the terminal, and git pull."
echo "   - Labels: $RUNNER_LABELS  (Indeed/Dice/LinkedIn will now run)."
echo "   - Check status anytime:  cd $RUNNER_DIR && sudo ./svc.sh status"
echo "   - Verify on GitHub:      ${REPO_URL}/settings/actions/runners"
