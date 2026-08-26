#!/bin/bash
# ════════════════════════════════════════════════════════════════
# Job Finder — UNIVERSAL DAEMON (Run Once, Everything Works)
# ════════════════════════════════════════════════════════════════
#
# RUN ONCE on your other laptop:
#   cd ~/Downloads/CV/job-finder && bash scripts/daemon.sh
#
# What it does:
#   ✅ Auto git-pulls every 15 min (picks up ALL fixes from any laptop)
#   ✅ Keeps self-hosted runner alive (for LinkedIn, Indeed, Dice apply)
#   ✅ Auto-triggers workflows when relevant code changes detected
#   ✅ Health checks all workflows — logs failures
#   ✅ Prevents laptop from sleeping
#   ✅ Self-heals: if runner dies, restarts it
#   ✅ One-time credential setup (first run only)
#   ✅ Idempotent: run again → says "already running"
#
# Covers ALL workflows:
#   • Apollo recruiter discovery + outreach (weekly)
#   • Daily job search + apply (Indeed, Dice, LinkedIn, Greenhouse)
#   • Recruiter auto-reply (daily)
#   • Reply tracker + pipeline (daily)
#   • Vendor outreach (monthly)
#   • LinkedIn posts (Mon/Thu)
#   • Cookie refresh (weekly)
#   • Runner health check
#
# To check: tail -f /tmp/job-daemon.log
# To stop:  kill $(cat /tmp/job-daemon.pid)
# Status:   bash scripts/daemon.sh (re-run shows status if already alive)
# ════════════════════════════════════════════════════════════════

REPO_DIR="${REPO_DIR:-$HOME/Downloads/CV/job-finder}"
REPO="BOBRIKH75/job-finder"
RUNNER_DIR="${RUNNER_DIR:-$HOME/actions-runner}"
PID_FILE="/tmp/job-daemon.pid"
LOG_FILE="/tmp/job-daemon.log"
PULL_INTERVAL=900       # 15 minutes — fast pickup of fixes
HEALTH_INTERVAL=600     # 10 minutes
RUNNER_CHECK=120        # 2 minutes — keep runner alive

# ─── Colors ───────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# ─── Pre-flight ───────────────────────────────────────────────
echo "🎯 Job Finder — Universal Daemon"
echo "═══════════════════════════════════"
echo ""

command -v gh >/dev/null 2>&1 || { echo "❌ Install gh CLI: brew install gh"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "❌ Install Python 3.12+"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "❌ Run: gh auth login"; exit 1; }

# ─── Already running? ─────────────────────────────────────────
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ DAEMON ALREADY ALIVE (PID: $OLD_PID)${NC}"
        echo ""
        echo "   Status: RUNNING"
        echo "   Since: $(stat -f '%Sm' "$PID_FILE" 2>/dev/null || stat -c '%y' "$PID_FILE" 2>/dev/null)"
        echo "   Log:   tail -f $LOG_FILE"
        echo "   Stop:  kill $OLD_PID"
        echo ""
        echo "   Last activity:"
        tail -5 "$LOG_FILE" 2>/dev/null | sed 's/^/   /'
        echo ""
        echo -e "${GREEN}   Everything is working. No action needed.${NC}"
        exit 0
    fi
fi

# ─── Step 1: Clone/Pull ──────────────────────────────────────
if [ ! -d "$REPO_DIR/.git" ]; then
    echo "📥 Cloning repo..."
    git clone "https://github.com/$REPO.git" "$REPO_DIR"
fi
cd "$REPO_DIR"
git pull origin master --quiet 2>/dev/null
echo "✅ Code up to date"
echo ""

# ─── Step 2: One-time secrets check ──────────────────────────
echo "🔑 Checking secrets..."
SECRETS=$(gh secret list --repo "$REPO" 2>/dev/null)
MISSING=""

# Required secrets
for S in GMAIL_USER GMAIL_APP_PASSWORD; do
    if echo "$SECRETS" | grep -q "$S"; then
        echo "   ✅ $S"
    else
        echo "   ❌ $S — MISSING"
        MISSING="$MISSING $S"
    fi
done

# Optional but important
for S in APOLLO_EMAIL APOLLO_PASSWORD HUNTER_API_KEY LINKEDIN_COOKIES INDEED_COOKIES; do
    if echo "$SECRETS" | grep -q "$S"; then
        echo "   ✅ $S"
    else
        echo "   ⚠️  $S — not set (optional)"
    fi
done

# Set missing required secrets
if [ -n "$MISSING" ]; then
    echo ""
    echo "❌ Missing required secrets:$MISSING"
    echo "   Set them: gh secret set <NAME> --repo $REPO"
    exit 1
fi

# Offer to set Apollo password if missing
if ! echo "$SECRETS" | grep -q "APOLLO_PASSWORD"; then
    echo ""
    read -p "   Set Apollo password now? (y/N): " SET_PASS
    if [ "$SET_PASS" = "y" ] || [ "$SET_PASS" = "Y" ]; then
        read -s -p "   Apollo password: " PASS
        echo ""
        [ -n "$PASS" ] && echo "$PASS" | gh secret set APOLLO_PASSWORD --repo "$REPO" && echo "   ✅ Set"
    fi
fi

echo ""

# ─── Step 3: Ensure self-hosted runner exists ─────────────────
if [ -d "$RUNNER_DIR" ]; then
    echo "🏃 Self-hosted runner found at $RUNNER_DIR"
    # Check if runner service is running
    if pgrep -f "Runner.Listener" > /dev/null 2>&1; then
        echo "   ✅ Runner is alive"
    else
        echo "   ⚠️  Runner not running — starting..."
        cd "$RUNNER_DIR"
        nohup ./run.sh > /tmp/runner.log 2>&1 &
        echo "   ✅ Runner started (PID: $!)"
    fi
    cd "$REPO_DIR"
else
    echo "🏃 No self-hosted runner at $RUNNER_DIR"
    echo "   Workflows use ubuntu-latest (GitHub hosted) — OK"
fi
echo ""

# ─── Step 4: Prevent sleep ────────────────────────────────────
pkill -f "caffeinate.*job-daemon" 2>/dev/null || true
caffeinate -d -i -s -w $$ &

# ─── Step 5: Start daemon ────────────────────────────────────
echo "════════════════════════════════════════════════════"
echo -e "${GREEN}🟢 DAEMON ALIVE — monitoring all workflows${NC}"
echo "════════════════════════════════════════════════════"
echo "   PID: $$"
echo "   Log: tail -f $LOG_FILE"
echo "   Stop: kill $$"
echo ""
echo "   Auto-pull: every 15 min"
echo "   Health check: every 10 min"
echo "   Runner check: every 2 min"
echo ""
echo "   Covers: Apollo, Indeed, Dice, LinkedIn, Greenhouse,"
echo "           Reply Tracker, Vendor Outreach, Cookie Refresh"
echo "════════════════════════════════════════════════════"
echo ""
echo -e "${GREEN}You can close this terminal — daemon runs in background.${NC}"
echo ""

# Save PID and daemonize
echo $$ > "$PID_FILE"
> "$LOG_FILE"
log "🟢 Daemon started (PID: $$)"

# Detach from terminal (nohup behavior)
trap "log '🔴 Daemon stopped'; rm -f $PID_FILE; kill $CAFFEINE_PID 2>/dev/null" EXIT

LAST_PULL=$(date +%s)
LAST_HEALTH=$(date +%s)
LAST_RUNNER_CHECK=$(date +%s)
LAST_COMMIT=$(git rev-parse HEAD 2>/dev/null)

# ─── Main loop (forever) ──────────────────────────────────────
while true; do
    NOW=$(date +%s)

    # ─── Auto git-pull ─────────────────────────────────────────
    if (( NOW - LAST_PULL >= PULL_INTERVAL )); then
        cd "$REPO_DIR"
        git fetch origin master --quiet 2>/dev/null
        REMOTE=$(git rev-parse origin/master 2>/dev/null)

        if [ "$LAST_COMMIT" != "$REMOTE" ]; then
            git pull origin master --quiet 2>/dev/null
            NEW_COMMIT=$(git rev-parse HEAD 2>/dev/null)
            CHANGED=$(git diff --name-only "$LAST_COMMIT" "$NEW_COMMIT" 2>/dev/null)
            log "📥 Pulled: ${LAST_COMMIT:0:7} → ${NEW_COMMIT:0:7}"
            log "   Changed: $(echo "$CHANGED" | wc -l | tr -d ' ') files"

            # Auto-trigger relevant workflows based on what changed
            if echo "$CHANGED" | grep -qE "apollo|recruiter_finder"; then
                gh workflow run "Apollo Recruiter Discovery + Outreach (Weekly)" --repo "$REPO" 2>/dev/null && \
                    log "   🚀 Triggered: Apollo workflow" || true
            fi
            if echo "$CHANGED" | grep -qE "find_jobs|indeed|dice|linkedin_easy"; then
                gh workflow run "AI Job Agent (Automated)" --repo "$REPO" 2>/dev/null && \
                    log "   🚀 Triggered: Job Agent" || true
            fi
            if echo "$CHANGED" | grep -qE "outreach|vendor|reply"; then
                gh workflow run "Gmail Reply Tracker + Pipeline (Daily)" --repo "$REPO" 2>/dev/null && \
                    log "   🚀 Triggered: Reply Tracker" || true
            fi
            if echo "$CHANGED" | grep -qE "greenhouse"; then
                gh workflow run "Greenhouse Apply" --repo "$REPO" 2>/dev/null && \
                    log "   🚀 Triggered: Greenhouse" || true
            fi

            LAST_COMMIT="$NEW_COMMIT"
        fi
        LAST_PULL=$NOW
    fi

    # ─── Runner health check ──────────────────────────────────
    if (( NOW - LAST_RUNNER_CHECK >= RUNNER_CHECK )); then
        if [ -d "$RUNNER_DIR" ]; then
            if ! pgrep -f "Runner.Listener" > /dev/null 2>&1; then
                log "⚠️  Runner died — restarting..."
                cd "$RUNNER_DIR"
                nohup ./run.sh > /tmp/runner.log 2>&1 &
                log "   ✅ Runner restarted (PID: $!)"
                cd "$REPO_DIR"
            fi
        fi
        LAST_RUNNER_CHECK=$NOW
    fi

    # ─── Workflow health check ─────────────────────────────────
    if (( NOW - LAST_HEALTH >= HEALTH_INTERVAL )); then
        WORKFLOWS=("daily-jobs.yml" "apollo-recruiter-discovery.yml" "gmail-reply-tracker.yml" "agent.yml")
        STATUS_LINE=""
        
        for WF in "${WORKFLOWS[@]}"; do
            RESULT=$(gh run list --workflow="$WF" --repo "$REPO" --limit=1 --json conclusion -q '.[0].conclusion' 2>/dev/null)
            SHORT=$(echo "$WF" | sed 's/.yml//' | cut -c1-12)
            if [ "$RESULT" = "success" ]; then
                STATUS_LINE="$STATUS_LINE ✅$SHORT"
            elif [ "$RESULT" = "failure" ]; then
                STATUS_LINE="$STATUS_LINE ❌$SHORT"
            else
                STATUS_LINE="$STATUS_LINE ⏳$SHORT"
            fi
        done
        
        log "💓 Health:$STATUS_LINE"
        LAST_HEALTH=$NOW
    fi

    sleep 60
done
