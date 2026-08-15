#!/usr/bin/env python3
"""
Extract LinkedIn session cookies and encode them for GitHub Secrets.

Run this on your LOCAL machine (not in CI) after logging in to LinkedIn in Chrome.

Steps:
1. Log in to LinkedIn in Chrome
2. Open DevTools (F12) → Application → Cookies → https://www.linkedin.com
3. Find these cookies and copy their values:
   - li_at      (required — main session token)
   - JSESSIONID (required — CSRF token)
   - liap       (optional but helpful)
4. Paste each value below when prompted
5. Copy the output and set it as GitHub Secret: LINKEDIN_COOKIES

Command to set the secret:
  gh secret set LINKEDIN_COOKIES --body "<paste output here>"
"""
import base64
import json


def main():
    print("LinkedIn Cookie Extractor")
    print("=" * 40)
    print("Paste cookie values from Chrome DevTools → Application → Cookies → linkedin.com")
    print()

    li_at = input("li_at value (required): ").strip()
    if not li_at:
        print("ERROR: li_at is required")
        return

    jsessionid = input("JSESSIONID value (required): ").strip()
    if not jsessionid:
        print("ERROR: JSESSIONID is required")
        return

    liap = input("liap value (optional, press Enter to skip): ").strip()

    cookies = [
        {
            "name": "li_at",
            "value": li_at,
            "domain": ".www.linkedin.com",
            "path": "/",
            "httpOnly": True,
            "secure": True,
        },
        {
            "name": "JSESSIONID",
            "value": jsessionid,
            "domain": ".www.linkedin.com",
            "path": "/",
            "httpOnly": False,
            "secure": True,
        },
    ]

    if liap:
        cookies.append({
            "name": "liap",
            "value": liap,
            "domain": ".www.linkedin.com",
            "path": "/",
            "httpOnly": True,
            "secure": True,
        })

    encoded = base64.b64encode(json.dumps(cookies).encode()).decode()

    print()
    print("=" * 40)
    print("Set this as GitHub Secret LINKEDIN_COOKIES:")
    print()
    print(encoded)
    print()
    print("Command:")
    print(f'  gh secret set LINKEDIN_COOKIES --body "{encoded}"')
    print()
    print("Cookies typically last ~1 year.")
    print("The bot will email you automatically if they expire.")


if __name__ == "__main__":
    main()
