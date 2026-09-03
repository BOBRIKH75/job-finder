#!/usr/bin/env python3
"""Dedicated Indeed applicator — Easy Apply with cookies.

Strategy:
1. Load Indeed cookies from INDEED_COOKIES env (base64 JSON) or local file
2. Search Indeed for Java C2C contract jobs using python-jobspy
3. For each Easy Apply job: click Apply → fill → submit
4. If cookie expired → log error, skip (refresh-cookies.yml handles refresh)
5. Save failed jobs to data/failed_jobs.json for solve-unsolved retry
"""
import base64
import json
import os
import random
import subprocess
import sys
import time

sys.path.insert(0, 'agent')

import indeed_learner

from src.memory import get_db, init_db, application_exists, upsert_application
from src.form_filler import load_profile
from src.questions_filler import fill_questions_page, is_questions_page


def load_indeed_cookies() -> list:
    """Load Indeed cookies from env (CI) or local file. Self-heals by extracting from Chrome."""
    env_cookies = os.environ.get('INDEED_COOKIES', '')
    if env_cookies:
        try:
            return json.loads(base64.b64decode(env_cookies))
        except Exception as e:
            print(f"⚠️ Failed to decode INDEED_COOKIES env: {e}")
    cookie_file = 'agent/data/indeed_cookies.json'
    if os.path.exists(cookie_file):
        try:
            cookies = json.loads(open(cookie_file).read())
            if cookies:
                return cookies
        except Exception:
            pass
    
    # Self-healing: extract from local Chrome (works on self-hosted runner)
    print("  🔄 No cookies — extracting from Chrome dynamically...")
    try:
        import browser_cookie3
        cj = browser_cookie3.chrome(domain_name='.indeed.com')
        cookies = [{"name": c.name, "value": c.value, "domain": c.domain,
                    "path": c.path, "secure": c.secure} for c in cj]
        if cookies:
            print(f"  ✅ Got {len(cookies)} Indeed cookies from Chrome")
            os.makedirs('agent/data', exist_ok=True)
            with open(cookie_file, 'w') as f:
                json.dump(cookies, f)
            # Update GitHub secret for next runs
            try:
                import subprocess
                encoded = base64.b64encode(json.dumps(cookies).encode()).decode()
                subprocess.run(["gh", "secret", "set", "INDEED_COOKIES", "--body", encoded,
                               "--repo", "BOBRIKH75/job-finder"], capture_output=True, timeout=15)
                print("  ✅ INDEED_COOKIES secret updated")
            except Exception:
                pass
            return cookies
    except ImportError:
        print("  ⚠️ browser-cookie3 not installed")
    except Exception as e:
        print(f"  ⚠️ Chrome extract failed: {str(e)[:60]}")
    
    # Fallback: try reading Chrome Cookies SQLite directly (macOS path)
    try:
        import sqlite3, shutil, tempfile
        chrome_cookie_path = os.path.expanduser(
            "~/Library/Application Support/Google/Chrome/Default/Cookies"
        )
        if os.path.exists(chrome_cookie_path):
            # Copy to temp (Chrome locks the file while running)
            tmp = tempfile.mktemp(suffix='.db')
            shutil.copy2(chrome_cookie_path, tmp)
            conn = sqlite3.connect(tmp)
            rows = conn.execute(
                "SELECT name, value, host_key, path, is_secure FROM cookies WHERE host_key LIKE '%indeed.com%'"
            ).fetchall()
            conn.close()
            os.remove(tmp)
            if rows:
                cookies = [{"name": r[0], "value": r[1], "domain": r[2],
                           "path": r[3], "secure": bool(r[4])} for r in rows if r[1]]
                if cookies:
                    print(f"  ✅ Got {len(cookies)} Indeed cookies from Chrome SQLite")
                    os.makedirs('agent/data', exist_ok=True)
                    with open(cookie_file, 'w') as f:
                        json.dump(cookies, f)
                    try:
                        import subprocess
                        encoded = base64.b64encode(json.dumps(cookies).encode()).decode()
                        subprocess.run(["gh", "secret", "set", "INDEED_COOKIES", "--body", encoded,
                                       "--repo", "BOBRIKH75/job-finder"], capture_output=True, timeout=15)
                        print("  ✅ INDEED_COOKIES secret updated")
                    except Exception:
                        pass
                    return cookies
            print("  ⚠️ No Indeed cookies in Chrome SQLite DB")
        else:
            print(f"  ⚠️ Chrome Cookies file not found at expected path")
    except Exception as e:
        print(f"  ⚠️ SQLite fallback failed: {str(e)[:60]}")
    
    return []


def load_failed_jobs(failed_file: str) -> list:
    """Load existing failed jobs from file."""
    if os.path.exists(failed_file):
        try:
            return json.loads(open(failed_file).read()).get('jobs', [])
        except (json.JSONDecodeError, KeyError):
            return []
    return []


def save_failed_jobs(failed_file: str, jobs: list) -> None:
    """Save failed jobs, keeping only last 200."""
    jobs = jobs[-200:]
    os.makedirs(os.path.dirname(failed_file), exist_ok=True)
    with open(failed_file, 'w') as f:
        json.dump({'jobs': jobs, 'count': len(jobs)}, f, indent=2)


# Human-like pause before clicks. 5s was too slow for volume (only a few
# jobs fit the CI budget). 1.5s default keeps it human-ish but lets us apply
# to many more jobs per run. Override with PRE_CLICK_WAIT.
PRE_CLICK_WAIT = float(os.environ.get('PRE_CLICK_WAIT', '1.5'))


def handle_robot_check(page) -> bool:
    """Detect and click an 'I'm not a robot' / verification checkbox.

    Handles the common variants:
      - reCAPTCHA checkbox (inside an iframe titled 'reCAPTCHA')
      - Cloudflare Turnstile ('Verify you are human')
      - Indeed's own 'Verify' / 'I'm not a robot' buttons
    Waits 5s first (page must settle), clicks, then waits again.
    Returns True if it clicked something.
    """
    clicked = False
    try:
        body = page.locator('body').inner_text(timeout=2500).lower()
    except Exception:
        body = ''
    signals = ['not a robot', 'verify you are human', 'are you a human',
               'unusual activity', 'recaptcha', 'verify you']
    looks_gated = any(s in body for s in signals)

    # Always try the reCAPTCHA / Turnstile iframe checkbox (it may not be in body text).
    try:
        for frame in page.frames:
            fname = (frame.name or '').lower()
            furl = (frame.url or '').lower()
            if 'recaptcha' in furl or 'turnstile' in furl or 'challenge' in furl or 'recaptcha' in fname:
                # Wait 5s before clicking so the widget is interactable.
                time.sleep(PRE_CLICK_WAIT)
                for sel in ['#recaptcha-anchor', 'div.recaptcha-checkbox-border',
                            'input[type="checkbox"]', 'label:has-text("not a robot")',
                            '.cb-c', 'span[role="checkbox"]']:
                    try:
                        el = frame.locator(sel)
                        if el.count() > 0 and el.first.is_visible(timeout=1500):
                            el.first.click()
                            clicked = True
                            print("  🤖 Clicked 'I'm not a robot' checkbox — waiting 5s...")
                            time.sleep(PRE_CLICK_WAIT)
                            break
                    except Exception:
                        continue
            if clicked:
                break
    except Exception:
        pass

    # Fallback: a plain 'Verify' / 'I'm not a robot' button on the main page.
    if not clicked and looks_gated:
        for sel in ['button:has-text("Verify")', 'button:has-text("I\'m not a robot")',
                    'button:has-text("I am not a robot")', 'input[type="checkbox"]']:
            try:
                el = page.locator(sel)
                if el.count() > 0 and el.first.is_visible(timeout=1500):
                    time.sleep(PRE_CLICK_WAIT)
                    el.first.click()
                    clicked = True
                    print("  🤖 Clicked verification control — waiting 5s...")
                    time.sleep(PRE_CLICK_WAIT)
                    break
            except Exception:
                continue
    return clicked


def safe_click(locator) -> bool:
    """Wait 5s (page settle / anti-bot) then click. Returns True on success."""
    try:
        time.sleep(PRE_CLICK_WAIT)
        locator.click()
        return True
    except Exception:
        return False


def _is_cloudflare(page) -> bool:
    """True if the current page is a Cloudflare challenge, not the real job."""
    try:
        if '__cf_chl' in (page.url or ''):
            return True
        for fr in page.frames:
            if 'cloudflare.com' in (fr.url or '') or 'challenges.cloudflare' in (fr.url or ''):
                return True
        body = page.locator('body').inner_text(timeout=2000).lower()
        return ('verify you are human' in body or 'checking your browser' in body
                or 'needs to review the security' in body)
    except Exception:
        return False


def wait_out_cloudflare(page, url: str, attempts: int = 3) -> bool:
    """DYNAMIC self-heal for Cloudflare challenges.

    Headed Chrome clears Cloudflare's JS challenge on its own, but it takes a
    few seconds. We poll for up to ~15s per attempt, and reload if stuck.
    Returns True once the real job page is showing (no CF challenge).
    """
    for attempt in range(1, attempts + 1):
        if not _is_cloudflare(page):
            return True
        print(f"  🛡️ Cloudflare challenge (attempt {attempt}/{attempts}) — waiting for auto-clear...")
        for _ in range(15):
            time.sleep(1)
            if not _is_cloudflare(page):
                print("  ✅ Cloudflare cleared")
                return True
        # Still stuck — reload and try again.
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=15000)
            time.sleep(3)
        except Exception:
            pass
    return not _is_cloudflare(page)


def main():
    db = get_db()
    init_db(db)
    profile = load_profile()
    cookies = load_indeed_cookies()

    if not cookies:
        print("❌ No Indeed cookies — run refresh-cookies workflow or save_indeed_cookies.py")
        print("   → Log into Indeed in Chrome on your laptop, then cookies will auto-extract")
        sys.exit(1)

    # Search Indeed for Java contract jobs
    try:
        from jobspy import scrape_jobs
        # Dynamic search queries - read from shared config (generated by find_jobs.py)
        import pandas as pd
        from datetime import datetime
        
        # Try to load dynamic queries from daily search config
        SEARCHES = []
        config_path = os.path.join(os.path.dirname(__file__), 'agent', 'data', 'search_queries.json')
        if os.path.exists(config_path):
            try:
                SEARCHES = json.load(open(config_path)).get('indeed', [])
            except Exception:
                pass
        
        if not SEARCHES:
            # Fallback - use profile-based queries
            SEARCHES = [
                'Java Spring Boot developer contract remote',
                'Senior Java backend microservices contract',
                'Java Kafka Kubernetes developer remote',
                'Java AWS developer contract C2C',
                'Spring Boot microservices engineer remote contract',
                'Java developer remote contract "easy apply"',
            ]
        
        # VOLUME vs TIME: searching too many queries (28 x 2 scrapes) ate the
        # entire 25-min CI budget on 2026-09-01 and the browser never launched.
        # Cap the query count and put a hard time budget on the whole search
        # phase, so most of the runtime is spent APPLYING (the real goal).
        max_queries = int(os.environ.get('MAX_QUERIES', '6'))
        search_budget_s = int(os.environ.get('SEARCH_BUDGET_S', '300'))  # 5 min
        queries = SEARCHES[:max_queries]
        search_start = time.time()

        all_jobs = []
        for q in queries:
            if time.time() - search_start > search_budget_s:
                print(f"  ⏱️ Search budget ({search_budget_s}s) reached — stopping search, moving to apply")
                break
            # One search per query (easy_apply=True) keeps it fast. The runtime
            # button-detection still catches applyable jobs the API mislabels.
            try:
                batch1 = scrape_jobs(
                    site_name=['indeed'],
                    search_term=q,
                    location='USA',
                    results_wanted=50,
                    easy_apply=True,
                )
                all_jobs.append(batch1)
                count1 = len(batch1)
            except Exception:
                count1 = 0

            count2 = 0
            if os.environ.get('DEEP_SEARCH', '0') == '1':
                try:
                    batch2 = scrape_jobs(
                        site_name=['indeed'],
                        search_term=q,
                        location='USA',
                        results_wanted=40,
                        hours_old=48,
                        job_type='contract',
                        is_remote=True,
                    )
                    all_jobs.append(batch2)
                    count2 = len(batch2)
                except Exception:
                    count2 = 0

            print(f"  🔍 '{q}' → {count1} (easy_apply) + {count2} (recent contract) = {count1+count2} jobs")
            if count1 == 0 and count2 == 0:
                print(f"  ⚠️ '{q}' returned 0 results from both searches")
        
        jobs = pd.concat(all_jobs, ignore_index=True).drop_duplicates(subset=['job_url']) if all_jobs else pd.DataFrame()
        print(f"🔍 Found {len(jobs)} Indeed jobs total (from {len(queries)} searches)")

        # CRITICAL: Filter to REAL Easy Apply jobs only.
        # Indeed's API 'easy_apply' filter is unreliable (returns 90%+ external redirect jobs).
        # True Easy Apply = job_url_direct is empty/NaN (no external redirect).
        # External = job_url_direct points to greenhouse, lever, workday, etc.
        if not jobs.empty and 'job_url_direct' in jobs.columns:
            before_count = len(jobs)
            # NOTE (verified live 2026-09-01): jobspy now populates job_url_direct
            # on ~100% of jobs, so the old "empty = Easy Apply" filter removed
            # EVERYTHING (0 jobs processed). We can no longer pre-filter reliably.
            # Instead: keep ALL jobs and let the runtime button-detection decide.
            # Rank likely-Easy-Apply first (indeed.com direct or empty) so the
            # MAX_APPS budget is spent on the best candidates before the rest.
            dd = jobs['job_url_direct'].astype(str)
            likely = jobs[dd.isin(['nan', '', 'None']) | dd.str.contains('indeed.com', na=False)]
            rest = jobs[~jobs.index.isin(likely.index)]
            jobs = pd.concat([likely, rest], ignore_index=True)
            print(f"  ℹ️ Kept {len(jobs)} jobs ({len(likely)} likely Easy Apply first, "
                  f"{len(rest)} checked at runtime). No pre-filter drop.")
        else:
            print(f"  ⚠️ No job_url_direct column — will detect Easy Apply at runtime")
    except Exception as e:
        print(f"⚠️ JobSpy search failed: {e}")
        return

    applied = 0
    failed = []
    # Load the self-learning selector store (grows every run).
    selectors_store = indeed_learner.load_store()
    indeed_learner.bump_runs(selectors_store)
    skipped = 0
    MAX_APPS = int(os.environ.get('MAX_APPS', '60'))
    # Apply-phase deadline: the CI step caps at 25 min. Leave a margin so we
    # always print results and save memory instead of being killed mid-loop.
    apply_deadline = time.time() + int(os.environ.get('APPLY_BUDGET_S', '1080'))  # 18 min

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ Playwright not installed — run: pip install playwright && playwright install chromium")
        return

    state_file = 'agent/data/indeed_state.json'
    with sync_playwright() as pw:
        # VERIFIED LIVE (2026-09-01): headless=True triggers Cloudflare on ~83%
        # of Indeed job pages (5/6 blocked). Headed mode passes 100% (6/6 reach
        # the apply button). This workflow runs on the self-hosted runner (your
        # laptop) which has a real display, so we default to HEADED. Override
        # with INDEED_HEADLESS=1 only for debugging on a headless box.
        headless = os.environ.get('INDEED_HEADLESS', '0') == '1'
        browser = pw.chromium.launch(
            headless=headless,
            args=['--disable-blink-features=AutomationControlled'],
        )
        print(f"🌐 Browser launched (headless={headless})")
        context = browser.new_context(
            user_agent=(
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/126.0.0.0 Safari/537.36'
            )
        )
        # Fix cookie format: Playwright needs boolean for 'secure', not int
        for c in cookies:
            c['secure'] = bool(c.get('secure', False))
        context.add_cookies(cookies)
        page = context.new_page()

        # Quick cookie validity check.
        # VERIFIED LIVE (2026-09-01): valid session redirects to
        # secure.indeed.com/settings and shows "sign out" (never "sign in").
        try:
            page.goto('https://www.indeed.com/account/view', wait_until='domcontentloaded', timeout=15000)
            time.sleep(2)
            page_text = page.locator('body').inner_text(timeout=3000).lower()
            logged_in = ('sign out' in page_text or 'log out' in page_text
                         or 'settings' in page.url or 'account' in page.url)
            if not logged_in:
                print("❌ Indeed cookies expired — skipping. Run refresh-cookies workflow.")
                browser.close()
                return
            print("✅ Indeed cookies valid")
        except Exception:
            print("⚠️ Cookie check inconclusive — proceeding anyway")

        for _, row in jobs.iterrows():
            if applied >= MAX_APPS:
                break
            if time.time() > apply_deadline:
                print("  ⏱️ Apply budget reached — stopping loop to save results")
                break

            url = str(row.get('job_url', ''))
            if not url or url == 'nan':
                continue

            if application_exists(db, url):
                skipped += 1
                continue

            title = str(row.get('title', ''))
            company = str(row.get('company', ''))

            try:
                page.goto(url, wait_until='domcontentloaded', timeout=15000)
                time.sleep(random.uniform(2, 4))

                # DYNAMIC self-heal: if Cloudflare challenged the page load,
                # wait for it to auto-clear (headed Chrome passes the JS
                # challenge on its own). Retry up to 3 times before giving up.
                cf_cleared = wait_out_cloudflare(page, url)
                if not cf_cleared:
                    reason = 'Cloudflare challenge did not clear'
                    failed.append({
                        'url': url, 'title': title, 'company': company,
                        'reason': reason, 'platform': 'indeed',
                        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    })
                    print(f"  🛡️ {title} @ {company}: {reason}")
                    time.sleep(random.uniform(3, 6))
                    continue

                # Anti-bot: if the page shows a robot/verification check, click it
                # and wait 5s so the real apply content renders.
                handle_robot_check(page)

                # SELF-LEARNING apply-button detection.
                # 1. Try every KNOWN selector, best-first (ranked by past wins).
                # 2. If none match, LEARN new selectors from the live page and
                #    retry them — so next run covers this variation too.
                # Every click waits 5s first (safe_click) to look human.
                clicked_selector = None
                for sel in indeed_learner.ranked_selectors(selectors_store):
                    try:
                        loc = page.locator(sel)
                        if loc.count() > 0 and loc.first.is_visible(timeout=1500):
                            if safe_click(loc.first):
                                clicked_selector = sel
                                indeed_learner.record_seen(selectors_store, sel)
                                break
                    except Exception:
                        continue

                if not clicked_selector:
                    # Nothing known worked — maybe a robot check is still up; retry it.
                    handle_robot_check(page)
                    # Scrape the page and learn any apply-like elements.
                    newly = indeed_learner.learn_from_page(selectors_store, page)
                    if newly:
                        print(f"  🧠 Learned {len(newly)} new selector(s) from: {title[:40]}")
                    for sel in newly:
                        try:
                            loc = page.locator(sel)
                            if loc.count() > 0 and loc.first.is_visible(timeout=1500):
                                if safe_click(loc.first):
                                    clicked_selector = sel
                                    indeed_learner.record_seen(selectors_store, sel)
                                    print(f"  🧠 New selector worked: {sel[:50]}")
                                    break
                        except Exception:
                            continue

                if clicked_selector:
                    time.sleep(random.uniform(2, 4))

                    # DRY_RUN walks the Continue wizard but does NOT click the
                    # final Submit (safe live test of the multi-step flow).
                    dry_run = os.environ.get('DRY_RUN', '0') == '1'

                    # Look for Continue/Submit in the apply modal.
                    # Each step: handle any robot check, then wait 5s before click.
                    submitted = False
                    # MULTI-STEP WIZARD (taught by Bobur + verified live 2026-09-01):
                    # After 'Apply with Indeed', SmartApply is a multi-page flow.
                    # On each page click 'Continue' until the final
                    # 'Submit your application' appears, then click it.
                    #
                    # CRITICAL DOM FACT (verified): the resume-selection page has
                    # SEVEN "Continue" buttons — SIX are HIDDEN (data-testid
                    # hp-continue-button-0/1/2) and only ONE is visible
                    # (data-testid="continue-button"). Using has-text().first
                    # clicked a HIDDEN button and the flow never advanced — THIS
                    # was the "can't click Continue" bug. Fix: target the real
                    # testids and always click the VISIBLE match.
                    CONTINUE_SELECTORS = [
                        '[data-testid="continue-button"]',
                        'button[data-testid="continue-button"]',
                        'button:has-text("Continue")',
                        'button:has-text("Next")',
                    ]
                    SUBMIT_SELECTORS = [
                        '[data-testid="submit-application-button"]',
                        'button:has-text("Submit your application")',
                        'button:has-text("Submit application")',
                        'button:has-text("Submit")',
                    ]
                    MAX_STEPS = int(os.environ.get('MAX_WIZARD_STEPS', '12'))

                    def _click_visible(selectors):
                        """Click the first VISIBLE match across selectors. Returns True on click.
                        Scrolls each candidate into view FIRST — the Continue/Submit button
                        is often below the fold on the questions/review pages."""
                        for sel in selectors:
                            loc = page.locator(sel)
                            for i in range(min(loc.count(), 8)):
                                el = loc.nth(i)
                                try:
                                    el.scroll_into_view_if_needed(timeout=2000)
                                except Exception:
                                    pass
                                try:
                                    if el.is_visible(timeout=1000):
                                        if safe_click(el):
                                            return True
                                except Exception:
                                    continue
                        return False
                    def _has_visible(selectors):
                        for sel in selectors:
                            loc = page.locator(sel)
                            for i in range(min(loc.count(), 8)):
                                el = loc.nth(i)
                                try:
                                    el.scroll_into_view_if_needed(timeout=2000)
                                except Exception:
                                    pass
                                try:
                                    if el.is_visible(timeout=800):
                                        return True
                                except Exception:
                                    continue
                        return False
                    def _answer_screening_questions():
                        """Fill empty REQUIRED screening fields so Continue can proceed.
                        Verified live 2026-09-01: the 50% 'Answer these questions'
                        page has required textareas + dropdowns that block Continue
                        when empty. Fills generic safe answers for Bob's profile."""
                        filled = 0
                        # 1. Textareas: answer by keyword, else a safe default.
                        try:
                            tas = page.locator('textarea:visible')
                            for i in range(min(tas.count(), 15)):
                                ta = tas.nth(i)
                                try:
                                    if (ta.input_value() or '').strip():
                                        continue  # already answered
                                    label = ''
                                    try:
                                        label = ta.evaluate(
                                            "el => { const w = el.closest('div'); return w ? (w.innerText||'') : ''; }"
                                        ).lower()
                                    except Exception:
                                        pass
                                    if 'earliest' in label or 'available' in label or 'start' in label:
                                        ans = 'Immediately / two weeks notice'
                                    elif 'requirement' in label or 'meet' in label or 'qualif' in label:
                                        ans = 'Yes, I meet the requirements outlined in the job description.'
                                    elif 'why' in label or 'interested' in label:
                                        ans = ('I am excited about the mission and the modern Java/Spring, '
                                               'microservices and cloud tech stack, and believe my backend '
                                               'experience is a strong fit.')
                                    elif 'background check' in label or 'clearance' in label or 'security' in label:
                                        ans = 'Yes, I am willing to complete a background check.'
                                    elif 'salary' in label or 'compensation' in label or 'rate' in label:
                                        ans = '80 per hour (negotiable)'
                                    else:
                                        ans = 'Yes'
                                    ta.scroll_into_view_if_needed(timeout=1500)
                                    ta.fill(ans)
                                    filled += 1
                                except Exception:
                                    continue
                        except Exception:
                            pass
                        # 2. Salary single-line inputs that got junk like "9".
                        try:
                            sal = page.locator('input:visible')
                            for i in range(min(sal.count(), 20)):
                                el = sal.nth(i)
                                try:
                                    lbl = el.evaluate("el => { const w = el.closest('div'); return w ? (w.innerText||'') : ''; }").lower()
                                    if 'salary' in lbl or 'compensation' in lbl:
                                        cur = (el.input_value() or '').strip()
                                        if cur == '' or cur.isdigit() and len(cur) <= 2:
                                            el.fill('80 per hour (negotiable)')
                                            filled += 1
                                except Exception:
                                    continue
                        except Exception:
                            pass
                        # 3. Required dropdowns still on 'Select an option'.
                        try:
                            sels = page.locator('select:visible')
                            for i in range(min(sels.count(), 15)):
                                dd = sels.nth(i)
                                try:
                                    lbl = dd.evaluate("el => { const w = el.closest('div'); return w ? (w.innerText||'') : ''; }").lower()
                                    val = dd.input_value()
                                    if val:
                                        continue
                                    opts = dd.evaluate("el => [...el.options].map(o => o.label || o.textContent)")
                                    chosen = None
                                    if 'state' in lbl:
                                        chosen = next((o for o in opts if 'colorado' in o.lower()), None)
                                    elif 'identif' in lbl or 'id' in lbl:
                                        chosen = next((o for o in opts if 'driver' in o.lower() or 'license' in o.lower() or 'passport' in o.lower()), None)
                                    if not chosen:
                                        # pick first real (non-placeholder) option
                                        chosen = next((o for o in opts if o and 'select' not in o.lower()), None)
                                    if chosen:
                                        dd.select_option(label=chosen)
                                        filled += 1
                                except Exception:
                                    continue
                        except Exception:
                            pass
                        if filled:
                            print(f"  ✍️ Auto-answered {filled} screening field(s)")
                        return filled

                    for step in range(MAX_STEPS):
                        handle_robot_check(page)
                        wait_out_cloudflare(page, page.url, attempts=2)

                        # 1. Submit page? click Submit and finish.
                        if _has_visible(SUBMIT_SELECTORS):
                            if dry_run:
                                print(f"  🧪 DRY_RUN reached SUBMIT page (step {step+1}) — NOT clicking: {title[:40]} @ {company}")
                                submitted = True
                                break
                            if _click_visible(SUBMIT_SELECTORS):
                                submitted = True
                                print(f"  📨 Clicked Submit (step {step+1})")
                                time.sleep(3)
                            break

                        # 2. Otherwise fill any required screening questions,
                        #    then advance with the VISIBLE Continue button.
                        #    Uses the self-learning answerer (memory -> profile ->
                        #    ask-user). Falls back to the old inline filler if the
                        #    module errors, so the flow never crashes.
                        try:
                            if is_questions_page(page):
                                fill_questions_page(page, db, profile, company=company)
                            else:
                                _answer_screening_questions()
                        except Exception as _qe:
                            print(f"  ⚠️ questions filler error: {str(_qe)[:60]} — using fallback")
                            _answer_screening_questions()
                        if _click_visible(CONTINUE_SELECTORS):
                            print(f"  ➡️ Clicked Continue (step {step+1})")
                            try:
                                page.wait_for_load_state('domcontentloaded', timeout=8000)
                            except Exception:
                                pass
                            time.sleep(random.uniform(1.5, 3))
                        else:
                            print(f"  ⚠️ No visible Continue/Submit at step {step+1} — stopping wizard")
                            break

                    # Check success
                    if dry_run and submitted:
                        applied += 1
                        indeed_learner.record_win(selectors_store, clicked_selector)
                        print(f"  🧪 DRY_RUN walked wizard to Submit: {title[:40]} @ {company}")
                        time.sleep(random.uniform(2, 4))
                        continue
                    page_text = page.locator('body').inner_text(timeout=3000).lower()
                    success_phrases = ['application submitted', 'applied', 'thank you',
                                       'your application has been submitted']
                    matched_phrase = next((s for s in success_phrases if s in page_text), None)
                    if matched_phrase:
                        applied += 1
                        # Proof of the confirmation ("thank you") page.
                        try:
                            os.makedirs('agent/screenshots', exist_ok=True)
                            shot = f"agent/screenshots/{int(time.time())}_confirmed.png"
                            page.screenshot(path=shot, full_page=True)
                            print(f"  📸 Confirmation saved: {shot} (matched: '{matched_phrase}')")
                        except Exception:
                            pass
                        # LEARN: this selector reached a real application — rank it up.
                        indeed_learner.record_win(selectors_store, clicked_selector)
                        upsert_application(
                            db,
                            company=company,
                            job_title=title,
                            job_url=url,
                            ats_type='indeed',
                            match_score=70,
                            status='applied',
                        )
                        print(f"  ✅ {title} @ {company}")
                    else:
                        reason = 'No success signal after submit'
                        failed.append({
                            'url': url,
                            'title': title,
                            'company': company,
                            'reason': reason,
                            'platform': 'indeed',
                            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                        })
                        print(f"  ❌ {title} @ {company}: {reason}")
                else:
                    reason = 'No Easy Apply button found (learned page, will retry variants next run)'
                    failed.append({
                        'url': url,
                        'title': title,
                        'company': company,
                        'reason': reason,
                        'platform': 'indeed',
                        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    })
                    print(f"  ⏭️ {title} @ {company}: no apply button (page learned)")

            except Exception as e:
                error_msg = str(e)[:100]
                # Detect cookie expiration during apply
                if 'sign in' in error_msg.lower() or 'login' in error_msg.lower():
                    print("⚠️ Indeed session expired mid-run — stopping")
                    break
                failed.append({
                    'url': url,
                    'title': title,
                    'company': company,
                    'reason': error_msg,
                    'platform': 'indeed',
                    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                })
                print(f"  ❌ {title} @ {company}: {error_msg[:60]}")

            # Human-like delay between applications
            time.sleep(random.uniform(3, 6))

        # Save refreshed storage state (cookies auto-renewed by Indeed during session)
        try:
            refreshed_state = context.storage_state()
            json.dump(refreshed_state, open(state_file, 'w'))
            # Update GitHub secret with refreshed cookies for next run
            refreshed_cookies = refreshed_state.get('cookies', [])
            if refreshed_cookies:
                encoded = base64.b64encode(json.dumps(refreshed_cookies).encode()).decode()
                subprocess.run(
                    ['gh', 'secret', 'set', 'INDEED_COOKIES', '--body', encoded, '--repo', 'BOBRIKH75/job-finder'],
                    capture_output=True, timeout=30
                )
                print(f"🔄 Refreshed {len(refreshed_cookies)} cookies → GitHub secret (auto-renewed)")
        except Exception as e:
            print(f"⚠️ Cookie refresh failed (non-fatal): {str(e)[:60]}")

        browser.close()

    # Persist what we learned this run so next run is smarter.
    indeed_learner.save_store(selectors_store)
    _learned = [s for s in selectors_store['selectors'] if s.get('source') == 'learned']
    print(f"🧠 Selector store: {len(selectors_store['selectors'])} total "
          f"({len(_learned)} learned), run #{selectors_store.get('runs', 0)}")

    # Save failed for solve-unsolved retry
    failed_file = 'agent/data/failed_jobs.json'
    existing = load_failed_jobs(failed_file)
    existing.extend(failed)
    save_failed_jobs(failed_file, existing)

    print(f"\n📊 Indeed Results:")
    print(f"  ✅ Applied: {applied}")
    print(f"  ❌ Failed:  {len(failed)} (saved for retry)")
    print(f"  ⏭️ Skipped: {skipped} (already applied)")


if __name__ == '__main__':
    main()
