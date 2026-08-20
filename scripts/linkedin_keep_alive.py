#!/usr/bin/env python3
"""
LinkedIn Session Keep-Alive — prevents cookie expiry by maintaining consistent activity.

Based on PhantomBuster research (thousands of users):
- LinkedIn resets cookies when activity is INCONSISTENT (gaps > 3-4 days)
- Running light activity daily keeps the session alive indefinitely
- The li_at cookie stays valid as long as the pattern looks human

This script does MINIMAL activity to keep the session warm:
1. Load LinkedIn with cookies
2. Visit feed page (simulates checking notifications)
3. Scroll a bit (looks human)
4. If session expired → try email/password login → export new cookies

Runs daily as a scheduled GitHub Actions job.
"""

import json
import os
import time
import random
import base64
from pathlib import Path
from datetime import datetime

LINKEDIN_COOKIES = os.environ.get("LINKEDIN_COOKIES", "")
LINKEDIN_EMAIL = os.environ.get("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.environ.get("LINKEDIN_PASSWORD", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def inject_cookies(context) -> bool:
    """Inject LinkedIn cookies into browser context."""
    if not LINKEDIN_COOKIES:
        return False
    cookies_to_set = []
    try:
        cookie_data = json.loads(LINKEDIN_COOKIES)
        if isinstance(cookie_data, list):
            for c in cookie_data:
                if isinstance(c, dict) and c.get("name") and c.get("value"):
                    cookies_to_set.append({
                        "name": c["name"],
                        "value": c["value"],
                        "domain": c.get("domain", ".linkedin.com"),
                        "path": c.get("path", "/"),
                    })
    except (json.JSONDecodeError, TypeError):
        for pair in LINKEDIN_COOKIES.split(";"):
            pair = pair.strip()
            if "=" in pair:
                name, value = pair.split("=", 1)
                cookies_to_set.append({
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": ".linkedin.com",
                    "path": "/",
                })
    if cookies_to_set:
        context.add_cookies(cookies_to_set)
        return True
    return False


def check_session_alive(page) -> bool:
    """Check if LinkedIn session is still valid."""
    page.goto("https://www.linkedin.com/feed/", timeout=30000)
    time.sleep(3)
    url = page.url.lower()
    if "login" in url or "authwall" in url or "signin" in url:
        return False
    # Check for feed content
    try:
        body = page.inner_text("body")[:2000].lower()
        if any(w in body for w in ["feed", "post", "connection", "network", "notifications"]):
            return True
    except Exception:
        pass
    return "feed" in url


def do_keep_alive_activity(page):
    """Minimal human-like activity to keep session warm."""
    print("  🔄 Performing keep-alive activity...")
    
    # Scroll feed slowly (like reading)
    for _ in range(3):
        page.evaluate("window.scrollBy(0, Math.random() * 500 + 200)")
        time.sleep(random.uniform(2, 5))
    
    # Visit notifications (common human action)
    try:
        page.goto("https://www.linkedin.com/notifications/", timeout=15000)
        time.sleep(random.uniform(2, 4))
    except Exception:
        pass
    
    # Visit jobs page briefly
    try:
        page.goto("https://www.linkedin.com/jobs/", timeout=15000)
        time.sleep(random.uniform(2, 4))
    except Exception:
        pass
    
    print("  ✅ Keep-alive activity done (feed + notifications + jobs)")


def try_login_and_export(page, context) -> str:
    """Try to login with email/password and export new cookies."""
    if not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
        print("  ❌ No LINKEDIN_EMAIL/PASSWORD — cannot auto-login")
        return ""
    
    print("  🔄 Attempting email/password login...")
    try:
        page.goto("https://www.linkedin.com/login", timeout=30000)
        time.sleep(3)
        
        # Fill login form
        page.fill('#username', LINKEDIN_EMAIL)
        time.sleep(1)
        page.fill('#password', LINKEDIN_PASSWORD)
        time.sleep(1)
        page.click('button[type="submit"]')
        time.sleep(8)
        
        # Check if login succeeded
        if "feed" in page.url or "mynetwork" in page.url:
            print("  ✅ Login successful!")
            # Export fresh cookies
            cookies = context.cookies()
            return json.dumps(cookies)
        
        # Check for verification challenge
        if "checkpoint" in page.url or "challenge" in page.url:
            print("  ⚠️ LinkedIn wants verification — cannot auto-solve")
            print("  📧 You need to login manually once from your browser")
            return ""
        
        print(f"  ❌ Login unclear — URL: {page.url}")
        return ""
        
    except Exception as e:
        print(f"  ❌ Login error: {str(e)[:80]}")
        return ""


def update_github_secret(new_cookies: str):
    """Update the LINKEDIN_COOKIES secret in GitHub via API."""
    if not GITHUB_TOKEN or not new_cookies:
        return False
    
    # This requires the gh CLI or GitHub API
    # For now, save to file and let the workflow commit it
    cookie_file = DATA_DIR / "linkedin_cookies_fresh.json"
    cookie_file.write_text(new_cookies)
    print(f"  📝 Fresh cookies saved to {cookie_file}")
    print("  ℹ️ Update secret manually: gh secret set LINKEDIN_COOKIES < data/linkedin_cookies_fresh.json")
    return True


def main():
    from playwright.sync_api import sync_playwright
    
    print("=" * 60)
    print(f"LINKEDIN SESSION KEEP-ALIVE — {datetime.now().strftime('%B %d, %Y %H:%M')}")
    print("=" * 60)
    
    if not LINKEDIN_COOKIES and not LINKEDIN_EMAIL:
        print("❌ No LINKEDIN_COOKIES or LINKEDIN_EMAIL set — nothing to do")
        return
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        
        # Inject cookies
        if inject_cookies(context):
            print("  🍪 Cookies injected")
        
        page = context.new_page()
        
        # Check if session is alive
        if check_session_alive(page):
            print("  ✅ LinkedIn session is ALIVE")
            # Do keep-alive activity
            do_keep_alive_activity(page)
            # Export updated cookies (LinkedIn refreshes them on activity)
            cookies = context.cookies()
            cookie_file = DATA_DIR / "linkedin_cookies_latest.json"
            cookie_file.write_text(json.dumps(cookies, indent=2))
            print(f"  💾 Updated cookies saved ({len(cookies)} cookies)")
        else:
            print("  ❌ LinkedIn session EXPIRED")
            # Try auto-login
            new_cookies = try_login_and_export(page, context)
            if new_cookies:
                update_github_secret(new_cookies)
                print("  ✅ Session restored via auto-login!")
            else:
                print("  ⚠️ Session expired — manual refresh needed")
                print("  📧 Run locally: python scripts/refresh_linkedin.py")
        
        browser.close()
    
    print(f"\n{'=' * 60}")
    print("KEEP-ALIVE COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
