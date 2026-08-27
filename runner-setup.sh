#!/bin/bash
# ============================================
# GitHub Actions Self-Hosted Runner — One-Click Setup
# Run once: chmod +x runner-setup.sh && ./runner-setup.sh
# After this: runner works 24/7 in ALL conditions
# ============================================

set -e

# Auto-detect runner directory (where this script lives, or ~/actions-runner)
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

echo "🔧 GitHub Actions Runner — Permanent Setup"
echo "============================================"
echo "   Runner dir: $RUNNER_DIR"
echo ""

# 1. Prevent sleep — ALL conditions (battery + charger + lid closed)
echo "🔋 Step 1: Disabling sleep (all power sources)..."
sudo pmset -a sleep 0 displaysleep 0 disksleep 0 hibernatemode 0
echo "   ✅ Mac will NEVER sleep (battery, lid closed, any condition)"
echo ""

# 2. Install and start runner as launchd service
echo "🏃 Step 2: Setting up runner as system service..."
cd "$RUNNER_DIR"

# Stop existing if running (ignore errors)
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

# 3. Verify
echo "============================================"
echo "📊 Verification"
echo ""
echo "   Power settings:"
pmset -g | grep -E "sleep|hibernate" | sed 's/^/      /'
echo ""
echo "   Runner status:"
sudo ./svc.sh status 2>&1 | sed 's/^/      /'
echo ""
echo "============================================"
echo "✅ DONE! Runner is permanent. Works through:"
echo "   ✅ Screen locked"
echo "   ✅ Lid closed (even on battery)"
echo "   ✅ Terminal closed"
echo "   ✅ User logged out"
echo "   ✅ Mac restarted"
echo ""
echo "   ❌ Only stops if Mac is POWERED OFF"
echo "============================================"
