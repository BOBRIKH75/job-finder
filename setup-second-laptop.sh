#!/usr/bin/env bash
#
# setup-second-laptop.sh — ONE command to turn a fresh Mac into a job-finder runner.
#
# Installs Homebrew + gh + git + Chrome, logs you into GitHub, clones the repo, then
# installs the self-hosted runner as a durable service (auto-start on login, restart on
# crash, sleep disabled) under a UNIQUE name so it does NOT replace your other laptop.
#
# USAGE (on the NEW laptop — copy/paste this whole line):
#   curl -fsSL https://raw.githubusercontent.com/BOBRIKH75/job-finder/master/setup-second-laptop.sh | RUNNER_NAME=bobur-laptop-2 bash
#
#   OR, if you already cloned the repo:
#     cd ~/Downloads/CV/job-finder && RUNNER_NAME=bobur-laptop-2 bash setup-second-laptop.sh
#
# Change RUNNER_NAME for each extra machine (bobur-laptop-2, -3, ...). Each one becomes its
# own runner and GitHub load-balances jobs across all of them.

set -uo pipefail

REPO="BOBRIKH75/job-finder"
REPO_DIR="$HOME/Downloads/CV/job-finder"
RUNNER_NAME="${RUNNER_NAME:-bobur-laptop-2}"

say(){ printf '\n➡️  %s\n' "$*"; }
ok(){  printf '✅ %s\n' "$*"; }
die(){ printf '\n❌ %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || die "This must run on a Mac (the runner labels are macOS)."

# ---- 1. Homebrew ----
if ! command -v brew >/dev/null 2>&1; then
  say "Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
    || die "Homebrew install failed"
  # add brew to PATH for this session (Apple Silicon + Intel paths)
  [ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
  [ -x /usr/local/bin/brew ]   && eval "$(/usr/local/bin/brew shellenv)"
fi
ok "Homebrew present"

# ---- 2. tools + real Chrome ----
say "Installing gh, git, Google Chrome..."
brew install gh git 2>/dev/null || true
command -v /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome >/dev/null 2>&1 \
  || brew install --cask google-chrome 2>/dev/null || true
ok "tools installed"

# ---- 3. GitHub login ----
if ! gh auth status >/dev/null 2>&1; then
  say "Log in to GitHub as BOBRIKH75 (a browser window will open)..."
  gh auth login --hostname github.com --git-protocol https --web \
    || die "gh login failed — run 'gh auth login' manually then re-run this script."
fi
ok "GitHub authenticated"

# ---- 4. clone (or update) the repo ----
if [ ! -d "$REPO_DIR/.git" ]; then
  say "Cloning $REPO ..."
  mkdir -p "$(dirname "$REPO_DIR")"
  git clone "https://github.com/${REPO}" "$REPO_DIR" || die "clone failed"
else
  say "Repo exists — pulling latest..."
  git -C "$REPO_DIR" pull --rebase --autostash || true
fi
ok "repo ready at $REPO_DIR"

# ---- 5. install the runner (unique name) via the existing fix-runner.sh ----
say "Installing the self-hosted runner as '$RUNNER_NAME' (durable service)..."
cd "$REPO_DIR"
RUNNER_NAME="$RUNNER_NAME" bash fix-runner.sh || die "fix-runner.sh failed"

# ---- 6. keep-awake LaunchAgent (survives reboot, no sudo) ----
say "Installing keep-awake agent so the laptop never sleeps..."
PLIST="$HOME/Library/LaunchAgents/com.bobur.jobrunner.caffeinate.plist"
cat > "$PLIST" <<'PL'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.bobur.jobrunner.caffeinate</string>
  <key>ProgramArguments</key><array><string>/usr/bin/caffeinate</string><string>-ims</string></array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/jobrunner-caffeinate.log</string>
  <key>StandardErrorPath</key><string>/tmp/jobrunner-caffeinate.log</string>
</dict></plist>
PL
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST" 2>/dev/null && ok "keep-awake agent loaded" || echo "   (load it manually: launchctl load $PLIST)"

cat <<EOF

=========================================================
✅ DONE — this Mac is now runner '$RUNNER_NAME'.
   • Registered as its OWN runner (does NOT replace your other laptop)
   • Installed as a service: auto-starts on login, restarts on crash
   • Keep-awake agent loaded (laptop won't sleep)

VERIFY both runners are online:
   gh api repos/${REPO}/actions/runners -q '.runners[] | "\(.name): \(.status)"'

⚠️  ONE manual step for Dice/Indeed/LinkedIn (cookies are per-machine):
   Open Chrome on THIS laptop and log into Dice + Indeed once, so the runner's
   browser profile has a valid session. (Greenhouse + the AI agent need nothing.)
=========================================================
EOF
