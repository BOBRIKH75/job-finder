#!/bin/bash
# ============================================================
# LinkedIn Easy Apply — Self-Hosted Runner Setup
# ============================================================
# This makes your laptop the runner for LinkedIn automation.
# LinkedIn sees YOUR home IP + YOUR Chrome = looks 100% like you.
#
# WHAT THIS DOES:
# 1. Downloads GitHub Actions runner to ~/actions-runner
# 2. Registers it with your repo
# 3. Starts it as a background service (survives reboot)
#
# AFTER THIS:
# - Leave your laptop open (lid can be closed if "prevent sleep" is on)
# - The LinkedIn Easy Apply workflow runs on YOUR machine
# - Uses YOUR IP address (not datacenter)
# - Can safely apply to 30-40 jobs/day (same as manual)
#
# TO STOP: launchctl unload ~/Library/LaunchAgents/actions.runner.plist
# TO START: launchctl load ~/Library/LaunchAgents/actions.runner.plist
# ============================================================

set -e

RUNNER_DIR="$HOME/actions-runner"
REPO="BOBRIKH75/job-finder"

echo "🚀 Setting up GitHub Actions self-hosted runner..."
echo "   Repo: $REPO"
echo "   Location: $RUNNER_DIR"
echo ""

# Step 1: Create runner directory
if [ -d "$RUNNER_DIR" ]; then
    echo "⚠️  $RUNNER_DIR already exists. Remove it first if you want a fresh install."
    echo "   rm -rf $RUNNER_DIR"
    exit 1
fi

mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"

# Step 2: Download latest runner for macOS
echo "📥 Downloading GitHub Actions runner..."
RUNNER_VERSION=$(curl -s https://api.github.com/repos/actions/runner/releases/latest | grep '"tag_name"' | sed 's/.*"v\(.*\)".*/\1/')
echo "   Version: $RUNNER_VERSION"

curl -o actions-runner.tar.gz -L "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-osx-arm64-${RUNNER_VERSION}.tar.gz"
tar xzf actions-runner.tar.gz
rm actions-runner.tar.gz

# Step 3: Get registration token from GitHub
echo ""
echo "📋 Getting registration token..."
TOKEN=$(gh api -X POST "repos/$REPO/actions/runners/registration-token" --jq '.token' 2>/dev/null)

if [ -z "$TOKEN" ]; then
    echo "❌ Failed to get token. Make sure 'gh' CLI is authenticated."
    echo "   Run: gh auth login"
    exit 1
fi

# Step 4: Configure the runner
echo ""
echo "⚙️  Configuring runner..."
./config.sh --url "https://github.com/$REPO" --token "$TOKEN" --name "bobur-laptop" --labels "self-hosted,macOS,linkedin" --unattended --replace

# Step 5: Install as launchd service (runs in background, survives reboot)
echo ""
echo "🔧 Installing as background service..."
./svc.sh install

# Step 6: Start the service
echo ""
echo "▶️  Starting runner service..."
./svc.sh start

echo ""
echo "============================================================"
echo "✅ DONE! Self-hosted runner is running."
echo ""
echo "   Status: ./svc.sh status"
echo "   Stop:   ./svc.sh stop"
echo "   Start:  ./svc.sh start"
echo "   Remove: ./svc.sh uninstall && ./config.sh remove --token \$TOKEN"
echo ""
echo "🔑 Your laptop is now a GitHub Actions runner."
echo "   LinkedIn workflows will run HERE using YOUR IP."
echo "   Leave your laptop on + connected to WiFi."
echo "============================================================"
