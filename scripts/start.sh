#!/bin/bash
# ════════════════════════════════════════════════════════════════
# Job Finder — START EVERYTHING (one command, never again)
# ════════════════════════════════════════════════════════════════
# Usage: bash scripts/start.sh
#
# Does:
#   1. git pull (latest code)
#   2. starts GitHub Actions runner (svc.sh start)
#   3. starts daemon (auto-pull, auto-trigger, self-heal)
#
# Run once after reboot. That's it.
# ════════════════════════════════════════════════════════════════

REPO_DIR="${REPO_DIR:-$HOME/Downloads/CV/job-finder}"
RUNNER_DIR="${RUNNER_DIR:-$HOME/actions-runner}"

echo "🚀 Job Finder — Starting Everything"
echo "════════════════════════════════════"
echo ""

# 1. Pull latest
cd "$REPO_DIR" 2>/dev/null || { echo "❌ Repo not found at $REPO_DIR"; exit 1; }
echo "📥 Pulling latest code..."
git pull origin master --quiet 2>/dev/null
echo "   ✅ Done"
echo ""

# 2. Start runner
if [ -d "$RUNNER_DIR" ]; then
    echo "🏃 Starting GitHub Actions runner..."
    cd "$RUNNER_DIR"
    ./svc.sh start 2>/dev/null || ./run.sh &>/dev/null &
    echo "   ✅ Runner started"
    cd "$REPO_DIR"
else
    echo "⚠️  No runner at $RUNNER_DIR — workflows use GitHub hosted (OK)"
fi
echo ""

# 3. Start daemon
echo "🔄 Starting daemon..."
bash scripts/daemon.sh
echo ""
echo "════════════════════════════════════"
echo "🟢 ALL RUNNING. Never touch again."
echo "════════════════════════════════════"
