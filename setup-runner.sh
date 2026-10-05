#!/usr/bin/env bash
#
# setup-runner.sh — one-command GitHub Actions self-hosted runner setup for job-finder.
#
# WHY THIS EXISTS:
#   The runner used to live INSIDE the repo folder, so every `git pull` wiped its
#   config (.runner / .credentials) → "Not configured" → runner died → Indeed/Dice/
#   LinkedIn jobs queued forever. This script installs the runner in a SEPARATE,
#   git-safe folder, registers it with the labels the workflows need (including the
#   `linkedin` label the old runner was missing), installs it as a background
#   service (survives reboot/sleep/terminal-close/git-pull), and disables Mac sleep.
#
# USAGE (on the runner laptop):
#   1. Get a fresh registration token (expires ~1 hour):
#        https://github.com/BOBRIKH75/job-finder/settings/actions/runners/new
#      Copy the long token (starts with "A...").
#   2. Run:
#        bash setup-runner.sh <TOKEN>
#   Re-run anytime with a fresh token to re-register.
#
set -euo pipefail

# ---- config ----
REPO_URL="https://github.com/BOBRIKH75/job-finder"
RUNNER_DIR="$HOME/gh-runner"                  # SEPARATE from the repo — git can't wipe it
RUNNER_NAME="bobur-laptop"
RUNNER_LABELS="self-hosted,macOS,linkedin"    # Indeed/Dice need self-hosted; LinkedIn needs linkedin

say(){ printf '\n➡️  %s\n' "$*"; }
die(){ printf '\n❌ %s\n' "$*" >&2; exit 1; }

# ---- 0. must be macOS ----
[ "$(uname -s)" = "Darwin" ] || die "This script is for macOS (the runner laptop)."

# ---- 1. token ----
TOKEN="${1:-}"
if [ -z "$TOKEN" ]; then
  die "No token given.
   Get one (expires ~1 hour):  ${REPO_URL}/settings/actions/runners/new
   Then run:                   bash setup-runner.sh <TOKEN>"
fi

# ---- 2. detect arch + latest runner version ----
ARCH="$(uname -m)"
if [ "$ARCH" = "arm64" ]; then PLAT="osx-arm64"; else PLAT="osx-x64"; fi

say "Detecting latest runner version from GitHub..."
VER="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest \
        | sed -n 's/.*"tag_name": *"v\{0,1\}\([0-9.]*\)".*/\1/p' | head -1)"
[ -n "$VER" ] || VER="2.337.0"   # fallback if the API is unreachable
PKG="actions-runner-${PLAT}-${VER}.tar.gz"
URL="https://github.com/actions/runner/releases/download/v${VER}/${PKG}"
say "arch=$ARCH  version=$VER  package=$PKG"

# ---- 3. clean up ANY existing runner on this machine (wherever it is) ----
say "Removing any existing runner service/config (so there's no conflict)..."
# a) known new location
if [ -d "$RUNNER_DIR" ]; then
  ( cd "$RUNNER_DIR" && sudo ./svc.sh stop 2>/dev/null || true )
  ( cd "$RUNNER_DIR" && sudo ./svc.sh uninstall 2>/dev/null || true )
  ( cd "$RUNNER_DIR" && ./config.sh remove --token "$TOKEN" 2>/dev/null || true )
fi
# b) any OTHER runner folder on the machine (e.g. an old one inside the repo)
#    found by its unmistakable svc.sh + config.sh pair, excluding our target dir.
while IFS= read -r other; do
  od="$(dirname "$other")"
  [ "$od" = "$RUNNER_DIR" ] && continue
  say "Found an old runner at: $od  → deregistering it"
  ( cd "$od" && sudo ./svc.sh stop 2>/dev/null || true )
  ( cd "$od" && sudo ./svc.sh uninstall 2>/dev/null || true )
  ( cd "$od" && ./config.sh remove --token "$TOKEN" 2>/dev/null || true )
done < <(find "$HOME" -maxdepth 6 -name "svc.sh" 2>/dev/null | grep -v "^$RUNNER_DIR/" || true)
# c) kill any stray foreground runner process
pkill -f Runner.Listener 2>/dev/null || true

# ---- 4. fresh install in the git-safe folder ----
say "Installing runner in: $RUNNER_DIR"
rm -rf "$RUNNER_DIR"; mkdir -p "$RUNNER_DIR"; cd "$RUNNER_DIR"
say "Downloading $PKG ..."
curl -fL -o runner.tar.gz "$URL" || die "Download failed: $URL"
tar xzf runner.tar.gz && rm -f runner.tar.gz

# ---- 5. register ----
say "Registering runner with GitHub (labels: $RUNNER_LABELS)..."
./config.sh --url "$REPO_URL" --token "$TOKEN" \
  --labels "$RUNNER_LABELS" --name "$RUNNER_NAME" --unattended --replace \
  || die "Registration failed — token may be expired. Get a fresh one and re-run."

# ---- 6. install as a background service ----
say "Installing as a background service (auto-restart on reboot/sleep/crash)..."
sudo ./svc.sh install
sudo ./svc.sh start
sleep 4
sudo ./svc.sh status || true

# ---- 7. keep the Mac awake ----
say "Disabling sleep so the runner stays online 24/7..."
sudo pmset -a sleep 0 disablesleep 1 2>/dev/null \
  || echo "   (couldn't change pmset — set 'never sleep' in System Settings → Battery)"

cat <<EOF

✅ DONE — runner '$RUNNER_NAME' installed in $RUNNER_DIR and running as a service.
   • git-safe: lives OUTSIDE the repo, so 'git pull' can never wipe it again.
   • labels:   $RUNNER_LABELS  → Indeed, Dice, AND LinkedIn will now run.
   • survives: reboot, sleep, closing the terminal.
   • status:   cd $RUNNER_DIR && sudo ./svc.sh status
   • verify:   ${REPO_URL}/settings/actions/runners
EOF
