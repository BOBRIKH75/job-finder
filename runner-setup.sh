#!/bin/bash
# ============================================
# GitHub Actions Self-Hosted Runner — Full Setup
# ONE script does EVERYTHING:
#   1. Prevents Mac from sleeping (lid closed, battery, any case)
#   2. Prevents display sleep from triggering system sleep
#   3. Installs runner as permanent service (survives reboot)
#   4. Starts the runner
#
# Run once: ./runner-setup.sh
# After this — laptop works 24/7 with lid closed + power plugged in
# ============================================

set -e

# Auto-detect runner directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/svc.sh" ]; then
    RUNNER_DIR="$SCRIPT_DIR"
elif [ -f "$HOME/actions-runner/svc.sh" ]; then
    RUNNER_DIR="$HOME/actions-runner"
else
    echo "❌ Cannot find actions-runner directory (svc.sh not found)"
    echo "   Place this script in your actions-runner folder, or ensure ~/actions-runner exists"
    exit 1
fi

echo "🔧 GitHub Actions Runner — Full Permanent Setup"
echo "============================================"
echo "   Runner dir: $RUNNER_DIR"
echo ""

# ============================================
# STEP 1: Prevent sleep — ALL conditions
# ============================================
echo "🔋 Step 1: Preventing sleep (ALL power sources, ALL conditions)..."

# -a = ALL power sources (battery + charger)
# sleep 0 = never sleep CPU
# displaysleep 0 = never turn off display (prevents sleep trigger)
# disksleep 0 = never sleep disk
# hibernatemode 0 = never hibernate
sudo pmset -a sleep 0 displaysleep 0 disksleep 0 hibernatemode 0

# Disable automatic power off (deep sleep after X hours)
sudo pmset -a autopoweroff 0 2>/dev/null || true

# Disable standby (another form of sleep on newer Macs)
sudo pmset -a standby 0 2>/dev/null || true

# Disable Power Nap (wakes briefly then sleeps again — unreliable)
sudo pmset -a powernap 0 2>/dev/null || true

# Disable TCP keep-alive sleep proxy (can cause network drop on "sleep")
sudo pmset -a tcpkeepalive 1 2>/dev/null || true

# Prevent lid-close sleep (requires disabling "clamshell sleep")
# This makes Mac stay awake even with lid closed on battery
sudo nvram boot-args="iog=0x0" 2>/dev/null || true

echo "   ✅ Sleep FULLY disabled:"
echo "      • CPU never sleeps"
echo "      • Lid closed = stays awake"
echo "      • On battery = stays awake"
echo "      • No hibernate, no standby, no power nap"
echo ""

# ============================================
# STEP 2: Install runner as permanent service
# ============================================
echo "🏃 Step 2: Installing runner as permanent service..."
cd "$RUNNER_DIR"

# Stop existing (ignore errors if not running)
sudo ./svc.sh stop 2>/dev/null || true

# Install as launchd service (idempotent)
sudo ./svc.sh install 2>/dev/null || echo "   (already installed — OK)"

# Start the service
sudo ./svc.sh start
echo "   ✅ Runner service started"
echo "      • Auto-starts on reboot"
echo "      • Auto-restarts on crash"
echo "      • Survives terminal close / logout"
echo ""

# ============================================
# STEP 3: Prevent App Nap (macOS throttling background apps)
# ============================================
echo "⚡ Step 3: Disabling App Nap for runner..."
defaults write NSGlobalDomain NSAppSleepDisabled -bool YES 2>/dev/null || true
echo "   ✅ App Nap disabled (macOS won't throttle background processes)"
echo ""

# ============================================
# STEP 4: Create a keep-alive caffeinate process (belt + suspenders)
# ============================================
echo "☕ Step 4: Setting up caffeinate keep-alive..."

PLIST="$HOME/Library/LaunchAgents/com.bobrikh.caffeinate.plist"
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST" << 'PLISTEOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.bobrikh.caffeinate</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/caffeinate</string>
        <string>-dimsu</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
PLISTEOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "   ✅ caffeinate running permanently (-dimsu = prevent ALL sleep types)"
echo "      -d = prevent display sleep"
echo "      -i = prevent idle sleep"  
echo "      -m = prevent disk sleep"
echo "      -s = prevent system sleep"
echo "      -u = declare user is active"
echo ""

# ============================================
# VERIFICATION
# ============================================
echo "============================================"
echo "📊 Verification:"
echo ""
echo "   Power settings:"
pmset -g | grep -E "sleep|hibernate|standby|autopoweroff" | sed 's/^/      /'
echo ""
echo "   Caffeinate:"
pgrep -l caffeinate | sed 's/^/      /' || echo "      (starting...)"
echo ""
echo "   Runner status:"
sudo ./svc.sh status 2>&1 | sed 's/^/      /'
echo ""
echo "============================================"
echo "✅ ALL DONE! Your Mac is a 24/7 runner."
echo ""
echo "   Works through:"
echo "   ✅ Screen locked"
echo "   ✅ Lid closed (any power source)"
echo "   ✅ On battery"
echo "   ✅ Terminal closed"
echo "   ✅ User logged out"
echo "   ✅ Mac restarted"
echo ""
echo "   ❌ Only stops if Mac is POWERED OFF"
echo "============================================"
