#!/usr/bin/env python3
"""Save Indeed login cookies for use in CI/CD.

Run ONCE locally with a visible browser:
    python3 save_indeed_cookies.py

This opens Indeed login page — you log in manually.
Cookies are saved to data/indeed_cookies.json.
Upload this file as a GitHub secret (base64 encoded) for CI use.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

COOKIES_FILE = Path(__file__).parent / "data" / "indeed_cookies.json"


def save_cookies():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)  # visible so you can log in
        context = browser.new_context()
        page = context.new_page()

        print("Opening Indeed login page...")
        page.goto("https://secure.indeed.com/auth")
        print("\n👉 LOG IN MANUALLY in the browser window.")
        print("   After you see the Indeed homepage, press ENTER here.\n")
        input("Press ENTER when logged in...")

        cookies = context.cookies()
        COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)
        COOKIES_FILE.write_text(json.dumps(cookies, indent=2))
        print(f"\n✅ Saved {len(cookies)} cookies to {COOKIES_FILE}")
        print(f"\nFor CI, base64 encode and add as GitHub secret:")
        print(f"  base64 -i {COOKIES_FILE} | pbcopy")
        print(f"  → Add as secret INDEED_COOKIES in GitHub repo settings")

        browser.close()


if __name__ == "__main__":
    save_cookies()
