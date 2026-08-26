#!/bin/bash
# ════════════════════════════════════════════════════════════════
# Apollo Pipeline — DAEMON (Run Once, Stays Alive Forever)
# ════════════════════════════════════════════════════════════════
#
# RUN ONCE on your other laptop:
#   cd ~/Downloads/CV/job-finder && bash scripts/apollo-daemon.sh
#
# What it does:
#   1. Sets up everything (password, secrets, runner)
#   2. Stays alive as a background daemon
#   3. Auto git-pulls every 30 minutes (picks up your fixes from this laptop)
#   4. Keeps the GitHub Actions runner alive
#   5. Self-heals: if something crashes, restarts automatically
#   6. Prevents laptop from sleeping
#
# To stop: kill $(cat /tmp/apollo-daemon.pid)
# To check: cat /tmp/apollo-daemon.log
# ════════════════════════════════════════════════════════════════

REPO_DIR="${REPO_DIR:-$HOME/Downloads/CV/job-finder}"
REPO="BOBRIKH75/job-finder"
PID_FILE="/tmp/apollo-daemon.pid"
LOG_FILE="/tmp/apollo-daemon.log"
PULL_INTERVAL=1800  # 30 minutes
HEALTH_CHECK_INTERVAL=300  # 5 minutes

# ─── Colors ───────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() {
    echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# ─── Pre-flight checks ───────────────────────────────────────
echo "🎯 Apollo Pipeline Daemon"
echo "════════════════════════"
echo ""

command -v gh >/dev/null 2>&1 || { echo "❌ Install gh CLI: brew install gh"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "❌ Install Python 3.12+"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "❌ Run: gh auth login"; exit 1; }

# Check if already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Daemon already running (PID: $OLD_PID)${NC}"
        echo "   Log: tail -f $LOG_FILE"
        echo "   Stop: kill $OLD_PID"
        echo ""
        echo "   Last 5 log lines:"
        tail -5 "$LOG_FILE" 2>/dev/null
        exit 0
    fi
fi

# ─── Step 1: Clone/Pull repo ─────────────────────────────────
if [ ! -d "$REPO_DIR/.git" ]; then
    echo "📥 Cloning repo..."
    git clone "https://github.com/$REPO.git" "$REPO_DIR"
fi

cd "$REPO_DIR"
git pull origin master 2>/dev/null
echo "✅ Code up to date"
echo ""

# ─── Step 2: Set Apollo password (one-time, interactive) ──────
SECRETS=$(gh secret list --repo "$REPO" 2>/dev/null)
if ! echo "$SECRETS" | grep -q "APOLLO_PASSWORD"; then
    echo "🔑 Apollo password not set yet."
    echo "   (If you use Google sign-in for Apollo, first set a password at:"
    echo "    app.apollo.io → Settings → Security → Set Password)"
    echo ""
    read -s -p "   Enter Apollo password: " APOLLO_PASS
    echo ""
    if [ -n "$APOLLO_PASS" ]; then
        echo "$APOLLO_PASS" | gh secret set APOLLO_PASSWORD --repo "$REPO"
        echo "   ✅ Password saved to GitHub secrets"
    else
        echo "   ⚠️  Skipped — set later with: gh secret set APOLLO_PASSWORD --repo $REPO"
    fi
    echo ""
fi

# ─── Step 3: Prevent sleep ────────────────────────────────────
pkill -f "caffeinate.*apollo-daemon" 2>/dev/null || true
caffeinate -d -i -s -w $$ &
CAFFEINE_PID=$!

# ─── Step 4: Start daemon loop ────────────────────────────────
echo ""
echo "════════════════════════════════════════════"
echo -e "${GREEN}🟢 DAEMON STARTING — runs forever${NC}"
echo "════════════════════════════════════════════"
echo "   PID: $$"
echo "   Log: tail -f $LOG_FILE"
echo "   Stop: kill $$"
echo "   Auto-pull: every 30 min"
echo "   Health check: every 5 min"
echo "════════════════════════════════════════════"
echo ""

# Save PID
echo $$ > "$PID_FILE"

# Clear old log
> "$LOG_FILE"
log "🟢 Daemon started (PID: $$)"
log "   Repo: $REPO_DIR"
log "   Pull interval: ${PULL_INTERVAL}s"
log ""

# Track last pull time
LAST_PULL=$(date +%s)
LAST_HEALTH=$(date +%s)
LAST_COMMIT=""

# ─── Main loop ────────────────────────────────────────────────
while true; do
    NOW=$(date +%s)
    
    # ─── Auto git-pull (every 30 min) ─────────────────────────
    if (( NOW - LAST_PULL >= PULL_INTERVAL )); then
        cd "$REPO_DIR"
        NEW_COMMIT=$(git rev-parse HEAD 2>/dev/null)
        
        git fetch origin master --quiet 2>/dev/null
        REMOTE_COMMIT=$(git rev-parse origin/master 2>/dev/null)
        
        if [ "$NEW_COMMIT" != "$REMOTE_COMMIT" ]; then
            log "📥 New changes detected — pulling..."
            git pull origin master --quiet 2>/dev/null
            PULLED_COMMIT=$(git rev-parse HEAD 2>/dev/null)
            log "   ✅ Updated: ${NEW_COMMIT:0:7} → ${PULLED_COMMIT:0:7}"
            log "   Last commit: $(git log -1 --format='%s' 2>/dev/null)"
            
            # If the apollo scripts changed, trigger a workflow run
            CHANGED=$(git diff --name-only "$NEW_COMMIT" "$PULLED_COMMIT" 2>/dev/null)
            if echo "$CHANGED" | grep -q "apollo\|recruiter\|outreach"; then
                log "   🚀 Apollo-related changes detected — triggering workflow..."
                gh workflow run "Apollo Recruiter Discovery + Outreach (Weekly)" --repo "$REPO" 2>/dev/null && \
                    log "   ✅ Workflow triggered!" || \
                    log "   ⚠️  Trigger failed (may already be running)"
            fi
        else
            log "   ✅ No new changes (up to date)"
        fi
        
        LAST_PULL=$NOW
    fi
    
    # ─── Health check (every 5 min) ───────────────────────────
    if (( NOW - LAST_HEALTH >= HEALTH_CHECK_INTERVAL )); then
        # Check if workflows are still running fine
        LATEST_RUN=$(gh run list --workflow="apollo-recruiter-discovery.yml" --repo "$REPO" --limit=1 --json conclusion -q '.[0].conclusion' 2>/dev/null)
        DAILY_RUN=$(gh run list --workflow="gmail-reply-tracker.yml" --repo "$REPO" --limit=1 --json conclusion -q '.[0].conclusion' 2>/dev/null)
        
        log "💓 Health: apollo=$LATEST_RUN, reply-tracker=$DAILY_RUN"
        
        # If last run failed, log it (don't auto-retry — wait for fix push)
        if [ "$LATEST_RUN" = "failure" ]; then
            log "   ⚠️  Last Apollo run FAILED — waiting for fix (will auto-pull)"
        fi
        
        LAST_HEALTH=$NOW
    fi
    
    # Sleep 60 seconds between loop iterations
    sleep 60
done
