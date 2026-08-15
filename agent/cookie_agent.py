#!/usr/bin/env python3
"""Cookie Refresh Agent — keeps Indeed session alive without manual login.

Runs as a scheduled GitHub Action (weekly) to refresh cookies before they expire.
Also manages rate limiting to avoid getting restricted.

Strategy:
1. Load existing cookies
2. Visit Indeed with cookies (validates session)
3. If session expired → use saved email/password to re-login
4. Save refreshed cookies back to GitHub secret (via API)
5. Rate limit: max 5 applies per day, random delays between actions
"""
import json, os, time, random, base64
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent / "data"
COOKIES_FILE = DATA_DIR / "indeed_cookies.json"
RATE_FILE = DATA_DIR / "rate_limits.json"

# Rate limits to avoid restriction
LIMITS = {
    "indeed": {"max_applies_per_day": 15, "min_delay_seconds": 20, "max_delay_seconds": 60},
    "greenhouse": {"max_applies_per_day": 200, "min_delay_seconds": 5, "max_delay_seconds": 15},
    "dice": {"max_applies_per_day": 15, "min_delay_seconds": 10, "max_delay_seconds": 30},
    "default": {"max_applies_per_day": 15, "min_delay_seconds": 10, "max_delay_seconds": 30},
}


def load_rate_state() -> dict:
    if RATE_FILE.exists():
        state = json.loads(RATE_FILE.read_text())
        # Reset if new day
        if state.get("date") != datetime.now().strftime("%Y-%m-%d"):
            return {"date": datetime.now().strftime("%Y-%m-%d"), "counts": {}}
        return state
    return {"date": datetime.now().strftime("%Y-%m-%d"), "counts": {}}


def save_rate_state(state: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RATE_FILE.write_text(json.dumps(state, indent=2))


def can_apply(site: str) -> bool:
    """Check if we can apply to this site without getting restricted."""
    state = load_rate_state()
    limit = LIMITS.get(site, LIMITS["default"])
    count = state["counts"].get(site, 0)
    return count < limit["max_applies_per_day"]


def record_apply(site: str):
    """Record an application to track rate limits."""
    state = load_rate_state()
    state["counts"][site] = state["counts"].get(site, 0) + 1
    save_rate_state(state)


def human_delay(site: str):
    """Wait a random human-like delay between actions."""
    limit = LIMITS.get(site, LIMITS["default"])
    delay = random.uniform(limit["min_delay_seconds"], limit["max_delay_seconds"])
    time.sleep(delay)


def refresh_indeed_cookies() -> bool:
    """Refresh Indeed cookies by visiting Indeed with existing session."""
    import cloakbrowser

    cookies = []
    # Load from file or env
    if COOKIES_FILE.exists():
        cookies = json.loads(COOKIES_FILE.read_text())
    elif os.environ.get("INDEED_COOKIES"):
        cookies = json.loads(base64.b64decode(os.environ["INDEED_COOKIES"]))

    if not cookies:
        print("  ❌ No Indeed cookies found")
        return False

    context = cloakbrowser.launch_context(headless=True)
    context.add_cookies(cookies)
    page = context.new_page()

    try:
        # Visit Indeed to refresh session
        page.goto("https://www.indeed.com/", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(3000)

        # Check if still logged in
        logged_in = page.evaluate('() => document.cookie.includes("indeed_rcc") || document.cookie.includes("CTK")')

        if logged_in:
            # Save refreshed cookies
            new_cookies = context.cookies()
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            COOKIES_FILE.write_text(json.dumps(new_cookies, indent=2))
            print(f"  ✅ Indeed cookies refreshed ({len(new_cookies)} cookies)")

            # Update GitHub secret if in CI
            if os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_ACTIONS"):
                _update_github_secret(new_cookies)

            context.close()
            return True
        else:
            print("  ⚠️ Indeed session expired — need manual re-login")
            print("  Run: python3 save_indeed_cookies.py")
            context.close()
            return False

    except Exception as e:
        print(f"  ❌ Cookie refresh failed: {e}")
        context.close()
        return False


def _update_github_secret(cookies: list):
    """Update INDEED_COOKIES GitHub secret via API."""
    import subprocess
    encoded = base64.b64encode(json.dumps(cookies).encode()).decode()
    # Use gh CLI if available
    result = subprocess.run(
        ["gh", "secret", "set", "INDEED_COOKIES", "--body", encoded],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        print("  ✅ GitHub secret updated")
    else:
        print(f"  ⚠️ Could not update GitHub secret: {result.stderr[:50]}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Refresh Indeed cookies")
    parser.add_argument("--status", action="store_true", help="Show rate limit status")
    args = parser.parse_args()

    if args.refresh:
        refresh_indeed_cookies()
    elif args.status:
        state = load_rate_state()
        print(f"Date: {state['date']}")
        for site, count in state.get("counts", {}).items():
            limit = LIMITS.get(site, LIMITS["default"])
            print(f"  {site}: {count}/{limit['max_applies_per_day']} applies today")
    else:
        print("Usage: python3 cookie_agent.py --refresh | --status")
