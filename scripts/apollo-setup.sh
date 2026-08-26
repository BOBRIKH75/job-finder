#!/bin/bash
# ════════════════════════════════════════════════════════════════
# Apollo Recruiter Pipeline — One-Time Setup
# ════════════════════════════════════════════════════════════════
# Run this from ANY laptop to set Apollo password and trigger.
#
# Usage:
#   cd ~/Downloads/CV/job-finder && bash scripts/apollo-setup.sh
#   OR (fresh machine):
#   git clone https://github.com/BOBRIKH75/job-finder.git
#   cd job-finder && bash scripts/apollo-setup.sh
# ════════════════════════════════════════════════════════════════

set -e
REPO="BOBRIKH75/job-finder"

echo "🎯 Apollo Recruiter Pipeline — Setup"
echo "════════════════════════════════════"
echo ""

# Check prerequisites
command -v gh >/dev/null 2>&1 || { echo "❌ Install gh CLI: brew install gh"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "❌ Login first: gh auth login"; exit 1; }

# Step 1: Pull latest code
echo "📥 Pulling latest code..."
git pull origin master 2>/dev/null || git clone "https://github.com/$REPO.git" .
echo "   ✅ Code up to date"
echo ""

# Step 2: Check if APOLLO_PASSWORD is already set (non-placeholder)
echo "🔑 Checking Apollo credentials..."
SECRETS=$(gh secret list --repo "$REPO" 2>/dev/null)

if echo "$SECRETS" | grep -q "APOLLO_PASSWORD"; then
    echo "   APOLLO_PASSWORD: exists"
    echo ""
    read -p "   Re-set password? (y/N): " RESET
    if [ "$RESET" != "y" ] && [ "$RESET" != "Y" ]; then
        echo "   Keeping existing password"
    else
        echo ""
        echo "   Enter your Apollo.io password:"
        echo "   (If you use Google sign-in, first set a password at:"
        echo "    app.apollo.io → Settings → Security → Set Password)"
        echo ""
        read -s -p "   Apollo Password: " APOLLO_PASS
        echo ""
        echo "$APOLLO_PASS" | gh secret set APOLLO_PASSWORD --repo "$REPO"
        echo "   ✅ APOLLO_PASSWORD updated"
    fi
else
    echo "   APOLLO_PASSWORD: NOT SET"
    echo ""
    echo "   Enter your Apollo.io password:"
    echo "   (If you use Google sign-in, first set a password at:"
    echo "    app.apollo.io → Settings → Security → Set Password)"
    echo ""
    read -s -p "   Apollo Password: " APOLLO_PASS
    echo ""
    echo "$APOLLO_PASS" | gh secret set APOLLO_PASSWORD --repo "$REPO"
    echo "   ✅ APOLLO_PASSWORD set"
fi

echo ""

# Step 3: Verify all required secrets exist
echo "🔍 Verifying all secrets..."
REQUIRED_SECRETS="APOLLO_EMAIL APOLLO_PASSWORD GMAIL_USER GMAIL_APP_PASSWORD"
ALL_GOOD=true

for SECRET in $REQUIRED_SECRETS; do
    if echo "$SECRETS" | grep -q "$SECRET"; then
        echo "   ✅ $SECRET"
    else
        echo "   ❌ $SECRET — MISSING"
        ALL_GOOD=false
    fi
done

if [ "$ALL_GOOD" = false ]; then
    echo ""
    echo "❌ Some secrets missing. Set them with:"
    echo "   gh secret set <NAME> --repo $REPO"
    exit 1
fi

echo ""

# Step 4: Trigger the workflow
echo "🚀 Triggering Apollo workflow..."
gh workflow run "Apollo Recruiter Discovery + Outreach (Weekly)" --repo "$REPO"
echo "   ✅ Workflow triggered!"
echo ""

# Step 5: Wait and show result
echo "⏳ Waiting for result (60s)..."
sleep 60

LATEST=$(gh run list --workflow="apollo-recruiter-discovery.yml" --repo "$REPO" --limit=1 --json status,conclusion,databaseId -q '.[0]')
STATUS=$(echo "$LATEST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null || echo "?")
CONCLUSION=$(echo "$LATEST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('conclusion','?'))" 2>/dev/null || echo "?")
RUN_ID=$(echo "$LATEST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('databaseId','?'))" 2>/dev/null || echo "?")

echo ""
echo "═══════════════════════════════════"
echo "📊 Result: status=$STATUS conclusion=$CONCLUSION"
echo "   Run: https://github.com/$REPO/actions/runs/$RUN_ID"
echo "═══════════════════════════════════"

if [ "$CONCLUSION" = "success" ]; then
    echo ""
    echo "🎉 SUCCESS! Apollo pipeline is fully operational."
    echo ""
    echo "   What happens now (automatic, no action needed):"
    echo "   • Every Monday 9 AM MT: Apollo finds recruiters → sends CV"
    echo "   • Every day 12 PM MT: Checks Gmail → classifies replies → auto-replies"
    echo "   • Cookies auto-refresh every 7 days (TTL)"
    echo ""
elif [ "$STATUS" = "in_progress" ] || [ "$STATUS" = "queued" ]; then
    echo ""
    echo "⏳ Still running. Check in 2 minutes:"
    echo "   gh run view $RUN_ID --repo $REPO"
else
    echo ""
    echo "⚠️  Check logs:"
    echo "   gh run view $RUN_ID --log --repo $REPO | tail -30"
fi
