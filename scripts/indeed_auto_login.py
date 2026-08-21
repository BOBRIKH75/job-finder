#!/usr/bin/env python3
"""Indeed Auto-Login — opens Chrome, waits for you to click Google Sign-In, saves cookies.

Run ONCE on your laptop. After that, cookies are saved and auto-refreshed.
Usage: python3 scripts/indeed_auto_login.py

This script:
1. Opens Indeed login page in a REAL Chrome window (not headless)
2. You click "Sign in with Google" (one click)
3. Script detects login success
4. Saves cookies to agent/data/indeed_cookies.json
5. Uploads to GitHub secret INDEED_COOKIES
6. Never needs to run again (weekly auto-refresh keeps it alive)
"""
import json, os, sys, time, base64, subprocess

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent'))

def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Installing playwright...")
        os.system("pip3 install playwright && python3 -m playwright install chromium")
        from playwright.sync_api import sync_playwright

    print("🔑 Indeed Auto-Login")
    print("=" * 40)
    print("Opening Indeed login page...")
    print("👉 Click 'Sign in with Google' when the browser opens")
    print("   (This is the ONLY manual step — ever)")
    print("")

    with sync_playwright() as pw:
        # Launch VISIBLE Chrome (not headless) so user can click Google login
        browser = pw.chromium.launch(headless=False, channel="chrome")
        context = browser.new_context()
        page = context.new_page()

        # Go to Indeed login
        page.goto("https://secure.indeed.com/auth?hl=en_US&co=US")
        print("⏳ Waiting for you to sign in (max 120 seconds)...")

        # Wait for login to complete (URL changes to indeed.com homepage or dashboard)
        start = time.time()
        while time.time() - start < 120:
            url = page.url
            if "indeed.com" in url and "auth" not in url and "secure" not in url:
                print(f"✅ Login detected! (redirected to {url[:50]})")
                break
            time.sleep(2)
        else:
            print("❌ Timeout — didn't detect login within 120 seconds")
            browser.close()
            return

        # Wait a moment for cookies to settle
        time.sleep(3)

        # Extract cookies
        cookies = context.cookies()
        indeed_cookies = [c for c in cookies if 'indeed' in c.get('domain', '')]

        if not indeed_cookies:
            print("❌ No Indeed cookies found after login")
            browser.close()
            return

        print(f"🍪 Got {len(indeed_cookies)} Indeed cookies")

        # Save locally
        cookie_file = os.path.join(os.path.dirname(__file__), '..', 'agent', 'data', 'indeed_cookies.json')
        os.makedirs(os.path.dirname(cookie_file), exist_ok=True)
        # Convert to simple format
        simple_cookies = [{"name": c["name"], "value": c["value"], "domain": c["domain"],
                          "path": c["path"], "secure": c.get("secure", False)} for c in indeed_cookies]
        with open(cookie_file, 'w') as f:
            json.dump(simple_cookies, f)
        print(f"💾 Saved to {cookie_file}")

        # Upload to GitHub secret
        try:
            encoded = base64.b64encode(json.dumps(simple_cookies).encode()).decode()
            result = subprocess.run(
                ["gh", "secret", "set", "INDEED_COOKIES", "--body", encoded,
                 "--repo", "BOBRIKH75/job-finder"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                print("☁️  INDEED_COOKIES secret updated on GitHub")
            else:
                print(f"⚠️  GitHub secret update failed: {result.stderr[:60]}")
        except Exception as e:
            print(f"⚠️  {str(e)[:60]}")

        browser.close()

    print("")
    print("✅ DONE! Indeed cookies saved. Auto-apply will work now.")
    print("   Weekly refresh keeps them alive — no manual step again.")


if __name__ == '__main__':
    main()
