#!/bin/bash
# =============================================================
# start.sh — One command: pull + register + start + keep alive
#
# Usage: cd ~/job-finder && ./runner/start.sh
#
# Does EVERYTHING automatically:
#   - Pulls latest code
#   - Stops old runner
#   - Re-registers with fresh token (fixes expired token)
#   - Starts runner service
#   - Prevents sleep
#   - Installs auto-start on reboot
# =============================================================

set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUNNER_DIR="$HOME/actions-runner"
REPO_URL="https://github.com/BOBRIKH75/job-finder"
LAUNCH_AGENT_LABEL="com.bobrikh.job-finder-runner"
LAUNCH_AGENT_PLIST="$HOME/Library/LaunchAgents/${LAUNCH_AGENT_LABEL}.plist"

echo "🚀 Job Finder Runner — Full Setup"
echo "========================================="
echo ""

# --- 1. Pull latest code ---
echo "📥 [1/7] Pulling latest code..."
cd "$REPO_DIR"
git pull origin master || true
echo ""

# --- 2. Stop everything ---
echo "🛑 [2/7] Stopping old runner..."
cd "$RUNNER_DIR"
sudo ./svc.sh stop 2>/dev/null || true
sudo ./svc.sh uninstall 2>/dev/null || true
pkill -f "Runner.Listener" 2>/dev/null || true
pkill -f "Runner.Worker" 2>/dev/null || true
sleep 2
echo "✅ Stopped"
echo ""

# --- 3. Get fresh token and re-register ---
echo "🔑 [3/7] Getting fresh registration token..."
TOKEN=$(gh api repos/BOBRIKH75/job-finder/actions/runners/registration-token --jq .token 2>/dev/null)

if [ -z "$TOKEN" ]; then
    echo "❌ Failed to get token. Make sure 'gh auth login' is done on this machine."
    exit 1
fi

echo "✅ Got token"
echo ""

echo "📝 [4/7] Registering runner..."
# Remove old config if exists
./config.sh remove --token "$TOKEN" 2>/dev/null || true

# Register fresh
./config.sh --url "$REPO_URL" --token "$TOKEN" --unattended --replace --name "bob-laptop" --labels "self-hosted,macOS"
echo "✅ Registered"
echo ""

# --- 5. Install and start service ---
echo "▶️  [5/7] Installing and starting service..."
sudo ./svc.sh install
sudo ./svc.sh start
echo "✅ Service running"
echo ""

# --- 6. Prevent sleep ---
echo "☕ [6/7] Preventing sleep..."
pkill -f caffeinate 2>/dev/null || true
caffeinate -dims &
sudo pmset -a displaysleep 0 sleep 0 disablesleep 1 2>/dev/null || true
echo "✅ Laptop will never sleep"
echo ""

# --- 7. Auto-start on reboot ---
echo "📌 [7/7] Installing auto-start on reboot..."
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$LAUNCH_AGENT_PLIST" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>${LAUNCH_AGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>cd ${RUNNER_DIR} &amp;&amp; ./run.sh</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>${RUNNER_DIR}/runner-stdout.log</string>
    <key>StandardErrorPath</key><string>${RUNNER_DIR}/runner-stderr.log</string>
</dict>
</plist>
PLIST
launchctl unload "$LAUNCH_AGENT_PLIST" 2>/dev/null || true
launchctl load "$LAUNCH_AGENT_PLIST"
echo "✅ Auto-start installed"
echo ""

# --- Done ---
echo "========================================="
echo "✅ ALL DONE"
echo "========================================="
echo ""
sudo ./svc.sh status
echo ""
echo "Runner registered, running, will survive reboot + screen lock."
echo "Keep laptop plugged in. That's it. 🎉"
echo ""
