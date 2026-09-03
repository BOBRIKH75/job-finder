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
        if any(s in body for s in ('log out', 'sign out', 'my profile', 'saved jobs',
                                   'application history', 'my dice')):
            return True
        if 'home-feed' in (page.url or '') or 'dashboard' in (page.url or ''):
            return True
        # logged-in users don't see a prominent 'sign in' CTA in the header
        try:
            if page.locator('[data-testid*="avatar" i], [aria-label*="account" i], '
                            'img[alt*="avatar" i]').count() > 0:
                return True
        except Exception:
            pass
        return False
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
        # MANUAL LOGIN MODE (DICE_MANUAL_LOGIN=1): open the login page and WAIT for the
        # user to log in by hand in this persistent-profile window. The session then
        # persists in .dice-profile for ALL future runs (no password automation needed).
        if not _logged_in(page) and os.environ.get('DICE_MANUAL_LOGIN') == '1':
            try:
                page.goto('https://www.dice.com/dashboard/login',
                          wait_until='domcontentloaded', timeout=30000)
            except Exception:
                pass
            print("  👤 MANUAL LOGIN: log into Dice in the open Chrome window now.")
            print("     Waiting up to 180s for login to complete...")
            for _ in range(60):
                time.sleep(3)
                if _logged_in(page):
                    break
            if _logged_in(page):
                try:
                    os.makedirs('data', exist_ok=True)
                    json.dump(ctx.cookies(), open(COOKIE_FILE, 'w'))
                    print("     🍪 login detected — saved cookies + profile persists for reuse")
                except Exception:
                    pass
        if not _logged_in(page):
            email = os.environ.get('DICE_EMAIL', '')
            pwd = os.environ.get('DICE_PASSWORD', '')
            if had_cookies:
                # cookies loaded but homepage login-signal not detected — the session may
                # still be valid; proceed to the search page (the real test) rather than bail.
                print("  2) cookies loaded; homepage login-signal not visible — proceeding to "
                      "search to verify session (jobs visible = logged in)")
            elif not email or not pwd:
                print("  2) NOT logged in. Either:")
                print("       • run with DICE_MANUAL_LOGIN=1 and log in by hand (persists), OR")
                print("       • add DICE_EMAIL/DICE_PASSWORD to agent/.env")
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
            cards = page.locator(
                'a[href*="/job-detail/"], [data-cy="card-title-link"], '
                '[data-testid="job-search-serp-card"], [data-id], '
                'div[role="listitem"], article').count()
        except Exception:
            cards = 0
        try:
            easy = page.locator('text=/easy apply/i').count()
        except Exception:
            easy = 0
        # jobs are present if we see either real cards OR easy-apply markers
        jobs_found = max(cards, easy)
        print(f"  3) Java Spring Boot remote easy-apply search → cards~{cards}, easy-apply markers~{easy}")
        # Re-check login on THIS (search) page — logged-in users see 'saved jobs'/avatar/'log out'.
        still_logged_in = _logged_in(page)
        print("\nVERDICT:")
        print(f"  - reachable: {not blocked}")
        print(f"  - logged in: {still_logged_in} (cookies saved: {os.path.exists(COOKIE_FILE)})")
        print(f"  - jobs found: {jobs_found}")
        if not blocked and jobs_found:
            print("  ✅ Stealth WORKS on Dice + jobs visible → a real apply flow is buildable (like Indeed).")
        elif blocked:
            print("  ❌ Still blocked even with patchright → Dice needs a different approach.")
        else:
            print("  ⚠️ Reachable but no jobs parsed — selector needs a tweak; markers may still show jobs exist.")
        ctx.close()


if __name__ == '__main__':
    main()
