#!/bin/bash
# ============================================================
# Job Agent — Quick Start (Run from ANY laptop)
# ============================================================
# 1. Clone repo (if not already cloned)
# 2. Prevent laptop sleep (caffeinate)
# 3. Set up self-hosted runner
# 4. Enable PREFER_SELF_HOSTED variable
# 5. Start applying with YOUR residential IP
#
# Expected daily applications (self-hosted, residential IP):
#   LinkedIn Easy Apply:  25 apps/day (1 run, weekdays)
#   AI Job Agent:         40 apps × 6 runs = up to 240 attempts/day
#   Dice Easy Apply:      75 apps/day (1 run, weekdays)
#   ─────────────────────────────────────────────────
#   TOTAL POTENTIAL:      ~100-150 successful apps/day
#   (some will fail: closed jobs, CAPTCHA, duplicates)
#   REALISTIC:            60-100 apps/day
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

# Step 1: PREVENT SLEEP — keep laptop awake while runner is active
echo "☕ Preventing laptop sleep (caffeinate)..."
# Kill any existing caffeinate from previous runs
pkill -f "caffeinate.*job-agent" 2>/dev/null || true
# Start caffeinate in background — prevents sleep even with lid closed
# -d: prevent display sleep, -i: prevent idle sleep, -s: prevent system sleep
caffeinate -d -i -s -w $$ &
CAFFEINE_PID=$!
echo "   PID: $CAFFEINE_PID (will stop when this script exits)"
echo "   ⚡ Laptop will NOT sleep until runner is stopped"
echo ""

# Also configure macOS to prevent sleep on AC power (permanent setting)
echo "⚙️  Configuring macOS power settings..."
# Prevent sleep when on power adapter (lid can be closed)
sudo pmset -a disablesleep 1 2>/dev/null && echo "   ✅ System sleep disabled" || echo "   ⚠️  Needs sudo for system-wide sleep prevention"
# Set display sleep to 10 min (saves power but runner keeps working)
sudo pmset -a displaysleep 10 2>/dev/null || true
# Prevent idle sleep
sudo pmset -a sleep 0 2>/dev/null || true
echo ""

# Step 2: Clone if needed
if [ ! -d "$CLONE_DIR" ]; then
    echo "📥 Cloning repo..."
    mkdir -p "$(dirname $CLONE_DIR)"
    gh repo clone "$REPO" "$CLONE_DIR"
else
    echo "📂 Repo exists, pulling latest..."
    cd "$CLONE_DIR" && git pull
fi

# Step 3: Enable self-hosted preference
echo ""
echo "⚙️  Enabling PREFER_SELF_HOSTED variable..."
gh variable set PREFER_SELF_HOSTED --body "true" --repo "$REPO" 2>/dev/null || \
    echo "   (variable may already exist)"

# Step 4: Set up self-hosted runner (if not already running)
if [ -d "$RUNNER_DIR" ] && "$RUNNER_DIR/svc.sh" status >/dev/null 2>&1; then
    echo ""
    echo "✅ Runner already active!"
    "$RUNNER_DIR/svc.sh" status
else
    echo ""
    echo "🔧 Setting up self-hosted runner..."
    bash "$CLONE_DIR/scripts/setup-self-hosted-runner.sh"
fi

# Step 5: Install Python dependencies (for local testing)
echo ""
echo "📦 Installing Python dependencies..."
cd "$CLONE_DIR/agent"
pip3 install -q -r requirements.txt 2>/dev/null
playwright install chromium 2>/dev/null || true

# Step 6: Create a persistent caffeinate that survives terminal close
echo ""
echo "☕ Setting up persistent sleep prevention..."
PLIST="$HOME/Library/LaunchAgents/com.bobrikh.job-agent-caffeine.plist"
cat > "$PLIST" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.bobrikh.job-agent-caffeine</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/caffeinate</string>
        <string>-d</string>
        <string>-i</string>
        <string>-s</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "   ✅ Caffeinate service installed (survives reboot)"

# Step 7: Show status
echo ""
echo "============================================================"
echo "✅ ALL SET! Your laptop is now applying to jobs 24/7."
echo ""
echo "📊 Expected daily applications (self-hosted, your IP):"
echo "   ┌──────────────────────────────────────────────────┐"
echo "   │ LinkedIn Easy Apply:  25 apps/run × 1 run = 25   │"
echo "   │ AI Job Agent:         40 apps/run × 6 runs = 240 │"
echo "   │ Dice Easy Apply:      75 apps/run × 1 run = 75   │"
echo "   │──────────────────────────────────────────────────│"
echo "   │ MAX ATTEMPTS:         ~340/day                    │"
echo "   │ REALISTIC SUCCESS:    60-100 apps/day             │"
echo "   │ (failures: closed jobs, CAPTCHAs, duplicates)     │"
echo "   └──────────────────────────────────────────────────┘"
echo ""
echo "🔋 Sleep prevention:"
echo "   ✅ caffeinate running (laptop won't sleep)"
echo "   ✅ System sleep disabled (works with lid closed)"
echo "   ✅ Survives reboot (launchd service)"
echo ""
echo "🔑 Credentials: GitHub Secrets (safe, not on disk)"
echo "   View: gh secret list --repo $REPO"
echo ""
echo "📋 Commands:"
echo "   Status:      ~/actions-runner/svc.sh status"
echo "   Stop:        ~/actions-runner/svc.sh stop"
echo "   Start:       ~/actions-runner/svc.sh start"
echo "   Test:        cd $CLONE_DIR/agent && python3 agent.py --dry-run"
echo "   Trigger now: gh workflow run 'AI Job Agent — Daily Run' --repo $REPO"
echo ""
echo "   STOP EVERYTHING (sleep + runner):"
echo "   ~/actions-runner/svc.sh stop"
echo "   launchctl unload ~/Library/LaunchAgents/com.bobrikh.job-agent-caffeine.plist"
echo "   sudo pmset -a disablesleep 0"
echo "============================================================"
