#!/usr/bin/env python3
"""Dice diagnostic — does patchright STEALTH get past Dice's headless block?

The old approach (undetected_chromedriver + --headless=new + --no-sandbox) was
detected → "click-counting, no real applies" → Dice workflow disabled.

This test uses the SAME stealth stack that beat Indeed:
  - patchright persistent real-Chrome context (channel="chrome", no fake UA/args)
  - HEADFUL by default (Dice, like Indeed, passes headed; headless is the tell)

It ONLY diagnoses (no applying): loads Dice, logs in (cookies if present, else
DICE_EMAIL/DICE_PASSWORD), searches Java jobs, counts how many show 'Easy apply'.

Run locally:
  cd ~/Downloads/CV/job-finder/agent
  # put DICE_EMAIL / DICE_PASSWORD in agent/.env (or export them), then:
  HEADFUL=1 python3 dice_probe.py
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, '.')
sys.path.insert(0, 'src')


def _load_env():
    for path in ('.env', 'agent/.env'):
        try:
            for line in open(path):
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except Exception:
            pass


_load_env()

try:
    from patchright.sync_api import sync_playwright
    _STEALTH = 'patchright'
except Exception:
    from playwright.sync_api import sync_playwright
    _STEALTH = 'playwright'

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.dice-profile')
COOKIE_FILE = 'data/dice_cookies.json'


def _launch(pw, headful):
    os.makedirs(PROFILE_DIR, exist_ok=True)
    for lock in ('SingletonLock', 'SingletonCookie', 'SingletonSocket'):
        try:
            os.unlink(os.path.join(PROFILE_DIR, lock))
        except OSError:
            pass
    kw = dict(user_data_dir=PROFILE_DIR, headless=not headful, no_viewport=True)
    if _STEALTH == 'patchright':
        kw['channel'] = 'chrome'
    try:
        ctx = pw.chromium.launch_persistent_context(**kw)
    except Exception:
        kw.pop('channel', None)
        ctx = pw.chromium.launch_persistent_context(**kw)
    return ctx


def _load_cookies(ctx):
    try:
        c = json.load(open(COOKIE_FILE))
        ctx.add_cookies(c)
        print(f"  🍪 loaded {len(c)} Dice cookies")
        return True
    except Exception:
        return False


def _logged_in(page):
    try:
        body = (page.locator('body').inner_text(timeout=3000) or '').lower()
        return 'log out' in body or 'sign out' in body or 'home-feed' in (page.url or '')
    except Exception:
        return False


def main():
    headful = os.environ.get('HEADFUL', '1') == '1'
    print(f"🚀 Dice probe — stealth={_STEALTH}, headful={headful}")
    with sync_playwright() as pw:
        ctx = _launch(pw, headful)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # 1) Can we even reach Dice without a block? (the old approach got detected)
        page.goto('https://www.dice.com/', wait_until='domcontentloaded', timeout=30000)
        time.sleep(3)
        title = (page.title() or '')[:60]
        blocked = any(s in (page.locator('body').inner_text(timeout=3000) or '').lower()
                      for s in ('access denied', 'are you a robot', 'verify you are human',
                                'unusual activity', 'blocked'))
        print(f"  1) reached dice.com — title={title!r} blocked={blocked}")

        # 2) Login: cookies first, else email/password
        had_cookies = _load_cookies(ctx)
        if had_cookies:
            page.reload(wait_until='domcontentloaded', timeout=20000)
            time.sleep(3)
        if not _logged_in(page):
            email = os.environ.get('DICE_EMAIL', '')
            pwd = os.environ.get('DICE_PASSWORD', '')
            if not email or not pwd:
                print("  2) NOT logged in and no DICE_EMAIL/DICE_PASSWORD in env "
                      "(add to agent/.env). Stopping — this is the blocker to fix.")
                ctx.close()
                return
            print("  2) logging in with email/password (2-step)...")
            try:
                page.goto('https://www.dice.com/dashboard/login',
                          wait_until='domcontentloaded', timeout=30000)
                time.sleep(3)
                page.fill('input[name="email"]', email, timeout=8000)
                time.sleep(1)
                for b in page.locator('button').all():
                    if 'continue with email' in (b.inner_text() or '').lower():
                        b.click(); break
                time.sleep(3)
                page.fill('input[name="password"]', pwd, timeout=8000)
                time.sleep(1)
                for b in page.locator('button').all():
                    if 'sign in' in (b.inner_text() or '').lower():
                        b.click(); break
                time.sleep(5)
            except Exception as e:
                print(f"     login error: {str(e)[:80]}")
            if _logged_in(page):
                # save cookies for next time (avoid re-login)
                try:
                    os.makedirs('data', exist_ok=True)
                    json.dump(ctx.cookies(), open(COOKIE_FILE, 'w'))
                    print("     🍪 saved Dice cookies for reuse")
                except Exception:
                    pass
        print(f"  2) logged in = {_logged_in(page)}")

        # 3) Search Java jobs + count 'Easy apply' (Dice's 1-click)
        page.goto('https://www.dice.com/jobs?q=Java%20Spring%20Boot&countryCode=US'
                  '&radius=30&radiusUnit=mi&page=1&pageSize=20&filters.easyApply=true'
                  '&filters.workplaceTypes=Remote',
                  wait_until='domcontentloaded', timeout=30000)
        time.sleep(4)
        try:
            cards = page.locator('[data-cy="card-title-link"], a[data-cy="card-title-link"], '
                                 '[data-testid="job-search-serp-card"]').count()
        except Exception:
            cards = 0
        try:
            easy = page.locator('text=/easy apply/i').count()
        except Exception:
            easy = 0
        print(f"  3) Java Spring Boot remote easy-apply search → cards~{cards}, easy-apply markers~{easy}")
        print("\nVERDICT:")
        print(f"  - reachable: {not blocked}")
        print(f"  - logged in: {_logged_in(page)}")
        print(f"  - jobs found: {cards}")
        if not blocked and _logged_in(page) and cards:
            print("  ✅ Stealth WORKS on Dice → a real apply flow is buildable (like Indeed).")
        elif blocked:
            print("  ❌ Still blocked even with patchright → Dice needs a different approach.")
        else:
            print("  ⚠️ Reachable but login/jobs incomplete — see above for the exact gap.")
        ctx.close()


if __name__ == '__main__':
    main()
