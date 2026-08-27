#!/bin/bash
# =============================================================
# start.sh — One command to keep the job-finder runner alive
# 
# Usage: ./runner/start.sh
# 
# What it does:
#   1. Pulls latest code from GitHub
#   2. Prevents laptop from sleeping (caffeinate)
#   3. Stops any old runner process
#   4. Starts the runner as a service (survives screen lock)
#   5. Installs a LaunchAgent to auto-start on boot
# =============================================================

set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUNNER_DIR="$HOME/actions-runner"
LAUNCH_AGENT_LABEL="com.bobrikh.job-finder-runner"
LAUNCH_AGENT_PLIST="$HOME/Library/LaunchAgents/${LAUNCH_AGENT_LABEL}.plist"

echo "🚀 Job Finder Runner — Starting..."
echo ""

# --- 1. Pull latest code ---
echo "📥 Pulling latest code..."
cd "$REPO_DIR"
git pull origin master --ff-only || git pull origin master
echo "✅ Code updated"
echo ""

# --- 2. Prevent sleep (background caffeinate) ---
# Kill any existing caffeinate from us
pkill -f "caffeinate.*job-finder" 2>/dev/null || true
caffeinate -dims -w $$ &
CAFFEINE_PID=$!
echo "☕ Sleep prevention active (PID: $CAFFEINE_PID)"
echo ""

# --- 3. Stop old runner ---
echo "🔄 Stopping old runner..."
cd "$RUNNER_DIR"
sudo ./svc.sh stop 2>/dev/null || true
# Also kill any lingering run.sh
pkill -f "Runner.Listener" 2>/dev/null || true
sleep 2
echo "✅ Old runner stopped"
echo ""

# --- 4. Start runner service ---
echo "▶️  Starting runner service..."
sudo ./svc.sh install 2>/dev/null || true
sudo ./svc.sh start
echo "✅ Runner service started"
echo ""

# --- 5. Install LaunchAgent for auto-start on boot ---
echo "📌 Installing auto-start on boot..."
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$LAUNCH_AGENT_PLIST" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LAUNCH_AGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>cd ${RUNNER_DIR} &amp;&amp; ./run.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${HOME}/actions-runner/runner-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${HOME}/actions-runner/runner-stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
PLIST

launchctl unload "$LAUNCH_AGENT_PLIST" 2>/dev/null || true
launchctl load "$LAUNCH_AGENT_PLIST"
echo "✅ Auto-start installed (survives reboot)"
echo ""

# --- 6. Disable screen sleep ---
echo "🖥️  Disabling display sleep..."
sudo pmset -a displaysleep 0 2>/dev/null || true
sudo pmset -a sleep 0 2>/dev/null || true
sudo pmset -a disablesleep 1 2>/dev/null || true
echo "✅ Laptop will never sleep"
echo ""

# --- 7. Verify ---
echo "========================================="
echo "✅ ALL DONE — Runner is alive and will stay alive"
echo "========================================="
echo ""
sudo ./svc.sh status
echo ""
echo "📊 Queued jobs will be picked up automatically."
echo "🔋 Keep laptop plugged in + open. That's it."
echo ""
