#!/bin/bash
# ============================================================
# Job Agent — Quick Start (Run from ANY laptop)
# ============================================================
# 1. Clone repo (if not already cloned)
# 2. Set up self-hosted runner
# 3. Enable PREFER_SELF_HOSTED variable
# 4. Start applying with YOUR residential IP
#
# Prerequisites:
#   - gh CLI installed and authenticated (gh auth login)
#   - Python 3.12+ installed
#   - Chrome installed (for LinkedIn/Indeed)
#
# Credentials: ALL stored in GitHub Secrets (never local)
#   - LINKEDIN_COOKIES, INDEED_COOKIES, RESEND_KEY, etc.
#   - Set via: gh secret set <NAME> --repo BOBRIKH75/job-finder
#
# Usage:
#   curl -sL https://raw.githubusercontent.com/BOBRIKH75/job-finder/master/scripts/quick-start.sh | bash
#   OR
#   cd ~/Downloads/CV/job-finder && bash scripts/quick-start.sh
# ============================================================

set -e

REPO="BOBRIKH75/job-finder"
RUNNER_DIR="$HOME/actions-runner"
CLONE_DIR="$HOME/Downloads/CV/job-finder"

echo "🚀 Job Agent — Quick Start"
echo "=========================="
echo ""

# Step 0: Check prerequisites
command -v gh >/dev/null 2>&1 || { echo "❌ Install gh CLI first: brew install gh"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "❌ Install Python 3.12+"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "❌ Run: gh auth login"; exit 1; }

# Step 1: Clone if needed
if [ ! -d "$CLONE_DIR" ]; then
    echo "📥 Cloning repo..."
    mkdir -p "$(dirname $CLONE_DIR)"
    gh repo clone "$REPO" "$CLONE_DIR"
else
    echo "📂 Repo exists, pulling latest..."
    cd "$CLONE_DIR" && git pull
fi

# Step 2: Enable self-hosted preference
echo ""
echo "⚙️  Enabling PREFER_SELF_HOSTED variable..."
gh variable set PREFER_SELF_HOSTED --body "true" --repo "$REPO" 2>/dev/null || \
    echo "   (variable may already exist)"

# Step 3: Set up self-hosted runner (if not already running)
if [ -d "$RUNNER_DIR" ] && "$RUNNER_DIR/svc.sh" status >/dev/null 2>&1; then
    echo ""
    echo "✅ Runner already active!"
    "$RUNNER_DIR/svc.sh" status
else
    echo ""
    echo "🔧 Setting up self-hosted runner..."
    bash "$CLONE_DIR/scripts/setup-self-hosted-runner.sh"
fi

# Step 4: Install Python dependencies (for local testing)
echo ""
echo "📦 Installing Python dependencies..."
cd "$CLONE_DIR/agent"
pip3 install -q -r requirements.txt 2>/dev/null
playwright install chromium 2>/dev/null || true

# Step 5: Show status
echo ""
echo "============================================================"
echo "✅ ALL SET! Your laptop is now applying to jobs."
echo ""
echo "📊 What's running:"
echo "   • AI Job Agent:    6x/day (every 2 hours, 9AM-5PM MT)"
echo "   • LinkedIn Apply:  1x/day (weekdays, 9AM MT)"
echo "   • Dice Apply:      1x/day (weekdays, 10:30AM MT)"
echo "   • Job Search:      2x/day (finds new jobs)"
echo ""
echo "🔑 Credentials are in GitHub Secrets (not on this machine)"
echo "   View: gh secret list --repo $REPO"
echo "   Add:  gh secret set <NAME> --repo $REPO"
echo ""
echo "📋 Commands:"
echo "   Status:    ~/actions-runner/svc.sh status"
echo "   Stop:      ~/actions-runner/svc.sh stop"
echo "   Start:     ~/actions-runner/svc.sh start"
echo "   Test run:  cd $CLONE_DIR/agent && python3 agent.py --dry-run"
echo "   Trigger:   gh workflow run 'AI Job Agent — Daily Run' --repo $REPO"
echo ""
echo "💡 Leave laptop open + connected to WiFi."
echo "   Close lid OK if 'Prevent sleep when display closed' is ON."
echo "   (System Preferences → Battery → Power Adapter → check it)"
echo "============================================================"
