#!/bin/bash
# ============================================================
# Job Agent — Keep Alive (run ONCE after setup)
# ============================================================
# Prevents laptop sleep and shows when jobs run.
# After this: close lid, walk away. It applies all day.
# ============================================================

echo "☕ Preventing sleep..."
sudo pmset -a disablesleep 1 2>/dev/null || echo "⚠️ Run with sudo for lid-close support"
sudo pmset -a sleep 0 2>/dev/null || true
sudo pmset -a displaysleep 10 2>/dev/null || true
pkill -f "caffeinate.*job-agent" 2>/dev/null || true
caffeinate -d -i -s &
echo "   ✅ Laptop will NOT sleep (even with lid closed)"
echo ""

echo "============================================================"
echo "📅 DAILY SCHEDULE (all automatic, no action needed):"
echo "============================================================"
echo ""
echo "   7:00 AM MT  — AI Job Agent (40 apps)"
echo "   9:00 AM MT  — AI Job Agent (40 apps) + LinkedIn Easy Apply (25 apps)"
echo "  10:30 AM MT  — Dice Easy Apply (75 apps)"
echo "  11:00 AM MT  — AI Job Agent (40 apps)"
echo "   1:00 PM MT  — AI Job Agent (40 apps)"
echo "   2:00 PM MT  — Daily C2C Job Search (finds new jobs)"
echo "   3:00 PM MT  — AI Job Agent (40 apps)"
echo "   5:00 PM MT  — AI Job Agent (40 apps)"
echo ""
echo "   TOTAL: ~60-100 successful applications per day"
echo ""
echo "============================================================"
echo "📋 COMMANDS (if you need them):"
echo "============================================================"
echo ""
echo "   Check status:     cd ~/actions-runner && ./svc.sh status"
echo "   See recent runs:  gh run list --repo BOBRIKH75/job-finder --limit 5"
echo "   Trigger manually: gh workflow run 'AI Job Agent — Daily Run' --repo BOBRIKH75/job-finder"
echo "   Stop runner:      cd ~/actions-runner && ./svc.sh stop"
echo "   Re-enable sleep:  sudo pmset -a disablesleep 0"
echo ""
echo "============================================================"
echo "✅ ALL SET. Close the lid. Walk away. It's applying."
echo "============================================================"
