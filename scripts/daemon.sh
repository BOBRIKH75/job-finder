#!/bin/bash
# ════════════════════════════════════════════════════════════════
# Job Finder — UNIVERSAL DAEMON
# ════════════════════════════════════════════════════════════════
# Run once → stays alive forever → never blocks your terminal
# Auto-pulls fixes, auto-triggers workflows, keeps runner alive
#
# Usage:
#   bash scripts/daemon.sh          → start in background (non-blocking)
#   bash scripts/daemon.sh status   → check if alive
#   bash scripts/daemon.sh stop     → kill daemon
#   bash scripts/daemon.sh logs     → tail live logs
#   bash scripts/daemon.sh fg       → foreground/blocking (debug only)
# ════════════════════════════════════════════════════════════════

REPO_DIR="${REPO_DIR:-$HOME/Downloads/CV/job-finder}"
REPO="BOBRIKH75/job-finder"
RUNNER_DIR="${RUNNER_DIR:-$HOME/actions-runner}"
PID_FILE="/tmp/job-daemon.pid"
LOG_FILE="/tmp/job-daemon.log"
PULL_INTERVAL=900
HEALTH_INTERVAL=600
RUNNER_CHECK=120

CMD="${1:-start}"

# ─── Helper ───────────────────────────────────────────────────
log() { echo "[$(date '+%H:%M:%S')] $1" >> "$LOG_FILE"; }

is_alive() {
    [ -f "$PID_FILE" ] && ps -p "$(cat "$PID_FILE" 2>/dev/null)" > /dev/null 2>&1
}

# ─── Commands ─────────────────────────────────────────────────
case "$CMD" in
    status)
        if is_alive; then
            echo "🟢 ALIVE (PID: $(cat $PID_FILE))"
            tail -5 "$LOG_FILE" 2>/dev/null | sed 's/^/   /'
        else
            echo "🔴 NOT RUNNING — start with: bash scripts/daemon.sh"
        fi
        exit 0 ;;
    stop)
        if is_alive; then
            kill "$(cat $PID_FILE)" 2>/dev/null
            rm -f "$PID_FILE"
            echo "🛑 Stopped"
        else
            echo "Not running"
        fi
        exit 0 ;;
    logs)
        exec tail -f "$LOG_FILE" ;;
    fg)
        ;; # continue to main loop below
    start|"")
        ;; # setup + fork below
    *)
        echo "Usage: daemon.sh [start|status|stop|logs|fg]"; exit 1 ;;
esac

# ─── Pre-flight ───────────────────────────────────────────────
command -v gh >/dev/null 2>&1 || { echo "❌ Need gh CLI: brew install gh"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "❌ Need: gh auth login"; exit 1; }

# Already alive?
if is_alive; then
    echo "🟢 Already running (PID: $(cat $PID_FILE)). Nothing to do."
    echo "   Logs: bash scripts/daemon.sh logs"
    exit 0
fi

# Pull latest
[ -d "$REPO_DIR/.git" ] || git clone "https://github.com/$REPO.git" "$REPO_DIR"
cd "$REPO_DIR" && git pull origin master --quiet 2>/dev/null

# One-time: Apollo password
SECRETS=$(gh secret list --repo "$REPO" 2>/dev/null)
if ! echo "$SECRETS" | grep -q "APOLLO_PASSWORD"; then
    echo "🔑 Apollo password not set."
    read -s -p "   Enter Apollo password (or Enter to skip): " PASS
    echo ""
    [ -n "$PASS" ] && echo "$PASS" | gh secret set APOLLO_PASSWORD --repo "$REPO" && echo "   ✅ Set"
fi

# Start runner if exists
if [ -d "$RUNNER_DIR" ] && ! pgrep -f "Runner.Listener" > /dev/null 2>&1; then
    cd "$RUNNER_DIR" && nohup ./run.sh > /tmp/runner.log 2>&1 &
    cd "$REPO_DIR"
fi

# ─── Fork to background (unless fg mode) ─────────────────────
if [ "$CMD" != "fg" ]; then
    echo ""
    echo "🟢 Starting daemon in background..."
    
    # Launch the loop as a detached background process
    nohup bash "$0" fg >> "$LOG_FILE" 2>&1 &
    DAEMON_PID=$!
    echo "$DAEMON_PID" > "$PID_FILE"
    
    # Keep laptop awake
    caffeinate -d -i -s -w "$DAEMON_PID" &>/dev/null &
    
    echo "   PID: $DAEMON_PID"
    echo "   Log: $LOG_FILE"
    echo ""
    echo "   Commands:"
    echo "     bash scripts/daemon.sh status"
    echo "     bash scripts/daemon.sh logs"
    echo "     bash scripts/daemon.sh stop"
    echo ""
    echo "🟢 Terminal is free. Daemon runs independently."
    echo "   Close terminal, close lid — it keeps working."
    exit 0
fi

# ─── Foreground mode: the actual loop ─────────────────────────
echo $$ > "$PID_FILE"
caffeinate -d -i -s -w $$ &>/dev/null &
trap "log '🔴 Stopped'; rm -f '$PID_FILE'" EXIT

log "🟢 Daemon started (PID: $$)"
LAST_PULL=$(date +%s)
LAST_HEALTH=$(date +%s)
LAST_RUNNER=$(date +%s)
LAST_COMMIT=$(cd "$REPO_DIR" && git rev-parse HEAD 2>/dev/null)

while true; do
    NOW=$(date +%s)
    cd "$REPO_DIR"

    # ── Auto git-pull (every 15 min) ──────────────────────────
    if (( NOW - LAST_PULL >= PULL_INTERVAL )); then
        git fetch origin master --quiet 2>/dev/null
        REMOTE=$(git rev-parse origin/master 2>/dev/null)

        if [ "$LAST_COMMIT" != "$REMOTE" ]; then
            git pull origin master --quiet 2>/dev/null
            CHANGED=$(git diff --name-only "$LAST_COMMIT" "$REMOTE" 2>/dev/null)
            COUNT=$(echo "$CHANGED" | wc -l | tr -d ' ')
            log "📥 Pulled $COUNT files (${LAST_COMMIT:0:7}→${REMOTE:0:7})"

            # Auto-trigger relevant workflows
            if echo "$CHANGED" | grep -qE "apollo|recruiter_finder"; then
                gh workflow run "Apollo Recruiter Discovery + Outreach (Weekly)" --repo "$REPO" 2>/dev/null && log "  🚀 Apollo triggered"
            fi
            if echo "$CHANGED" | grep -qE "find_jobs|indeed|dice|linkedin_easy|agent\.py"; then
                gh workflow run "AI Job Agent (Automated)" --repo "$REPO" 2>/dev/null && log "  🚀 Agent triggered"
            fi
            if echo "$CHANGED" | grep -qE "outreach|vendor|reply|smart_reply"; then
                gh workflow run "Gmail Reply Tracker + Pipeline (Daily)" --repo "$REPO" 2>/dev/null && log "  🚀 Reply tracker triggered"
            fi
            if echo "$CHANGED" | grep -qE "greenhouse"; then
                gh workflow run "Greenhouse Apply" --repo "$REPO" 2>/dev/null && log "  🚀 Greenhouse triggered"
            fi
            if echo "$CHANGED" | grep -qE "linkedin_easy"; then
                gh workflow run "LinkedIn Easy Apply" --repo "$REPO" 2>/dev/null && log "  🚀 LinkedIn triggered"
            fi

            LAST_COMMIT="$REMOTE"
        fi
        LAST_PULL=$NOW
    fi

    # ── Runner health (every 2 min) ───────────────────────────
    if (( NOW - LAST_RUNNER >= RUNNER_CHECK )); then
        if [ -d "$RUNNER_DIR" ] && ! pgrep -f "Runner.Listener" > /dev/null 2>&1; then
            log "⚠️ Runner died — restarting"
            cd "$RUNNER_DIR" && nohup ./run.sh > /tmp/runner.log 2>&1 &
            cd "$REPO_DIR"
        fi
        LAST_RUNNER=$NOW
    fi

    # ── Workflow health (every 10 min) ─────────────────────────
    if (( NOW - LAST_HEALTH >= HEALTH_INTERVAL )); then
        S=""
        for WF in daily-jobs apollo-recruiter-discovery gmail-reply-tracker agent; do
            R=$(gh run list --workflow="${WF}.yml" --repo "$REPO" --limit=1 --json conclusion -q '.[0].conclusion' 2>/dev/null)
            case "$R" in
                success) S="$S ✅${WF:0:8}" ;;
                failure) S="$S ❌${WF:0:8}" ;;
                *)       S="$S ⏳${WF:0:8}" ;;
            esac
        done
        log "💓$S"
        LAST_HEALTH=$NOW
    fi

    sleep 60
done
