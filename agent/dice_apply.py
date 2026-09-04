#!/usr/bin/env python3
"""Dice Easy-Apply — same proven pattern as Indeed/Greenhouse.

Flow: patchright stealth (persistent real Chrome + cookie session) → search Java/Spring
remote easy-apply jobs → CV-fit gate (cv_match) → 5-layer dedup (job-id + persistent
title JSON + in-memory + DB claim-lock) → open job → click Easy Apply → fill questions
(questions_filler) → submit → record. Self-learning failed/dead tracking (no re-loop).

Login: uses data/dice_cookies.json + the .dice-profile persistent session (log in once via
dice_probe.py DICE_MANUAL_LOGIN=1). CI: provide DICE_COOKIES secret (base64 of the cookies).

Run locally:
  cd ~/Downloads/CV/job-finder/agent
  HEADFUL=1 DICE_TARGET=5 python3 dice_apply.py
"""
import base64
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

from src.memory import get_db, init_db, application_exists, upsert_application, claim_job, release_claim
from src.form_filler import load_profile
try:
    from src.cv_match import should_apply
except Exception:
    should_apply = None
try:
    from questions_filler import fill_questions_page, is_questions_page
except Exception:
    try:
        from src.questions_filler import fill_questions_page, is_questions_page
    except Exception:
        fill_questions_page = is_questions_page = None

# Profile lives in the RUNNER'S REAL HOME. NOTE: actions/checkout TEMPORARILY OVERRIDES $HOME
# to a temp dir, so os.path.expanduser('~') is WRONG under CI (points to a temp folder → always
# logged out — this is why CI couldn't see the manual login). Resolve the REAL home via the
# login user (pwd) so manual login + every CI run share ONE persistent ~/.dice-profile.
def _real_home():
    if os.environ.get('DICE_PROFILE_DIR'):
        return None  # explicit override wins
    try:
        import pwd as _pwd
        return _pwd.getpwuid(os.getuid()).pw_dir   # real home, ignores $HOME override
    except Exception:
        return os.path.expanduser('~')

_HOME = _real_home()
PROFILE_DIR = os.environ.get('DICE_PROFILE_DIR') or os.path.join(_HOME, '.dice-profile')
COOKIE_FILE = os.environ.get('DICE_COOKIE_FILE') or os.path.join(PROFILE_DIR, 'dice_cookies.json')
APPLIED_FILE = 'agent/data/dice_applied.json' if os.path.isdir('agent') else 'data/dice_applied.json'
JK_FILE = 'data/dice_applied_ids.json'
FAILED_FILE = 'data/dice_failed_ids.json'
DEAD_FILE = 'data/dice_dead_ids.json'
MAX_FAILS = int(os.environ.get('MAX_FAILS_PER_JOB', '3'))


# ---- dedup helpers (same pattern as greenhouse) ----
def _norm_title(t):
    t = (t or '').lower()
    t = re.sub(r'\(.*?\)', ' ', t)
    t = re.sub(r'\b(sr|senior|jr|junior|lead|staff|principal|remote|w2|c2c|contract|us|usa)\b', ' ', t)
    return ' '.join(re.sub(r'[^a-z0-9 ]', ' ', t).split())


def _title_key(company, title):
    c = ' '.join((company or '').lower().split())
    t = _norm_title(title)
    return f"{c}|{t}" if t else ''


def _load_json_set(path):
    try:
        return set(json.load(open(path)))
    except Exception:
        return set()


def _save_json_set(path, s):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump(sorted(s), open(path, 'w'), indent=0)
    except Exception:
        pass


def _load_dead():
    try:
        d = json.load(open(DEAD_FILE))
        if isinstance(d, dict):
            return d
        # tolerate a list format (e.g. from a merge) -> convert to {id: MAX_FAILS}
        if isinstance(d, list):
            return {str(x): MAX_FAILS for x in d}
        return {}
    except Exception:
        return {}


LESSONS_FILE = 'data/dice_lessons.json'


def _load_dice_lessons():
    try:
        return json.load(open(LESSONS_FILE))
    except Exception:
        return {}


def _record_dice_lesson(reason):
    """SELF-LEARNING (Bobur): remember WHY an apply failed so the NEXT run auto-applies a
    fix. reason -> {count, fix}. Fixes are consumed by _apply_one via env flags set at start."""
    lessons = _load_dice_lessons()
    e = lessons.get(reason, {'count': 0, 'fix': None})
    e['count'] += 1
    e['fix'] = {
        'no_apply_button': 'longer_button_wait',   # button rendered late → wait longer
        'incomplete': 'more_wizard_steps',          # wizard had more steps → more steps + settle
        'error': 'reload_retry',                    # transient → reload + retry once
        'login_redirect': 'need_fresh_login',       # session expired → prompt manual login
    }.get(reason, e.get('fix'))
    lessons[reason] = e
    try:
        os.makedirs('data', exist_ok=True)
        json.dump(lessons, open(LESSONS_FILE, 'w'), indent=2)
        print(f"  🧠 learned: {reason} → fix='{e['fix']}' (seen {e['count']}x)")
    except Exception:
        pass


def _apply_lessons_to_env():
    """At run start, read past lessons and set env flags so _apply_one self-heals this run."""
    lessons = _load_dice_lessons()
    for reason, e in lessons.items():
        fix = (e or {}).get('fix')
        if fix == 'longer_button_wait':
            os.environ.setdefault('DICE_BTN_WAIT', '15000')      # 15s button wait (was 8s)
        elif fix == 'more_wizard_steps':
            os.environ.setdefault('DICE_WIZARD_STEPS', '12')     # more steps (was 8)
            os.environ.setdefault('DICE_STEP_SETTLE', '3')       # longer settle between steps
    if lessons:
        print(f"  🧠 self-heal: applied {len(lessons)} learned lesson(s) to this run")


def _job_id(url):
    m = re.search(r'/job-detail/([0-9a-f-]+)', url or '')
    return m.group(1) if m else ''


# ---- browser ----
def _launch(pw, headful):
    os.makedirs(PROFILE_DIR, exist_ok=True)
    # DEBUG: show the exact profile path CI uses + whether it holds a session (Cookies file)
    _cookies_db = os.path.join(PROFILE_DIR, 'Default', 'Cookies')
    print(f"  📁 profile: {PROFILE_DIR}  (exists={os.path.isdir(PROFILE_DIR)}, "
          f"session_db={os.path.exists(_cookies_db)}, HOME_env={os.environ.get('HOME','')})", flush=True)
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
    # cookies: env secret (CI) or file (local)
    cookies = None
    env = os.environ.get('DICE_COOKIES', '').strip()
    if env:
        try:
            cookies = json.loads(base64.b64decode(env).decode() if not env.startswith('[') else env)
        except Exception:
            cookies = None
    if cookies is None:
        try:
            cookies = json.load(open(COOKIE_FILE))
        except Exception:
            cookies = []
    if cookies:
        try:
            ctx.add_cookies(cookies)
        except Exception:
            pass
    return ctx


def _posted_date_filter():
    """Freshness logic (Bobur): burst through the backlog for the first week, then apply
    ONLY to the LATEST jobs. Tracks the first-run date in data/dice_first_run.json; after
    7 days, restrict Dice search to jobs posted in the last 7 days (filters.postedDate=SEVEN).
    Override anytime with DICE_POSTED_DATE (ONE/THREE/SEVEN/'' for all)."""
    override = os.environ.get('DICE_POSTED_DATE')
    if override is not None:
        return override.strip()
    marker = 'data/dice_first_run.json'
    try:
        first = float(json.load(open(marker)).get('ts', 0))
    except Exception:
        first = 0.0
    if not first:
        try:
            os.makedirs('data', exist_ok=True)
            json.dump({'ts': time.time()}, open(marker, 'w'))
        except Exception:
            pass
        return ''   # week 1 → apply to all (clear the backlog)
    age_days = (time.time() - first) / 86400.0
    return 'SEVEN' if age_days >= 7 else ''   # after 1 week → last-7-days jobs only


def _search_urls(page, term, want=50, pages=3):
    """Return [(url, title)] of easy-apply jobs from a Dice search, across N pages."""
    q = term.replace(' ', '%20')
    posted = _posted_date_filter()
    pd = f'&filters.postedDate={posted}' if posted else ''
    out = []
    for pg_num in range(1, pages + 1):
        try:
            page.goto(f'https://www.dice.com/jobs?q={q}&countryCode=US&page={pg_num}&pageSize={want}'
                      f'&filters.easyApply=true&filters.workplaceTypes=Remote{pd}',
                      wait_until='domcontentloaded', timeout=30000)
            time.sleep(4)
            rows = page.evaluate(r"""() => {
                const out = [];
                for (const a of document.querySelectorAll('a[data-testid="job-search-job-card-link"]')) {
                    const label = a.getAttribute('aria-label') || '';
                    const title = label.replace(/^View Details for /, '').replace(/\s*\([0-9a-f]+\)\s*$/, '');
                    const href = a.getAttribute('href') || '';
                    if (href.includes('/job-detail/')) out.push({title: title.trim(), href});
                }
                return out;
            }""") or []
        except Exception:
            rows = []
        if not rows:
            break   # no more pages
        base = 'https://www.dice.com'
        out += [(base + r['href'] if r['href'].startswith('/') else r['href'], r['title']) for r in rows]
    return out


def _apply_one(page, url, title):
    """Open a Dice job, click Easy Apply, fill questions, submit. Returns result str."""
    page.goto(url, wait_until='domcontentloaded', timeout=30000)
    time.sleep(3)
    # company from the detail page (for dedup/record)
    company = ''
    try:
        company = page.evaluate(
            """() => {
                const el = document.querySelector('a[href*="/company/"], [data-cy="companyNameLink"], [data-testid*="company" i]');
                return el ? el.textContent.trim().slice(0,60) : '';
            }""") or ''
    except Exception:
        company = ''
    # detect session-expired redirect (apply needs login) → distinct reason for self-heal
    if 'login' in (page.url or '').lower():
        return 'login_redirect', company
    # Dice shows an "Applied" state on the button for jobs already applied to (Bobur's tip).
    # Trust Dice's own state → skip immediately (also covers applies made outside our dedup files).
    try:
        already = page.evaluate(r"""() => {
            const btn = document.querySelector('[data-testid="apply-button"], button, a');
            const scan = (document.body.innerText || '').toLowerCase();
            // button text or a page badge that means already-applied
            const phrases = ['application submitted', 'you applied', "you've applied",
                             'already applied', 'applied on', 'application sent'];
            // check the apply control text first (most reliable)
            const controls = Array.from(document.querySelectorAll('[data-testid="apply-button"], button, a'));
            for (const c of controls) {
                const t = (c.textContent || '').trim().toLowerCase();
                if (t === 'applied' || t === 'application submitted' || t.startsWith('applied')) return true;
            }
            return phrases.some(p => scan.includes(p));
        }""")
        if already:
            print(f"  ⏭️ Dice says ALREADY APPLIED — skip: {title[:40]}")
            return 'already_applied', company
    except Exception:
        pass
    # find + click Apply (Dice uses <a data-testid="apply-button">Apply Now</a>)
    clicked = False
    # wait for the apply control to render (learned: DICE_BTN_WAIT longer if it rendered late)
    _btn_wait = int(os.environ.get('DICE_BTN_WAIT', '8000'))
    try:
        page.wait_for_selector('[data-testid="apply-button"], a:has-text("Apply Now"), '
                               'button:has-text("Easy apply")', timeout=_btn_wait)
    except Exception:
        pass
    for sel in ['[data-testid="apply-button"]',
                'a:has-text("Apply Now")',
                'button:has-text("Easy apply")',
                'button:has-text("Easy Apply")',
                'a:has-text("Apply")',
                'button:has-text("Apply")']:
        try:
            loc = page.locator(sel)
            if loc.count() and loc.first.is_visible(timeout=2000):
                loc.first.scroll_into_view_if_needed(timeout=2000)
                try:
                    loc.first.click(timeout=4000)
                except Exception:
                    loc.first.evaluate("(b) => b.click()")
                clicked = True
                break
        except Exception:
            continue
    if not clicked:
        return 'no_apply_button', company
    time.sleep(4)
    _wizard_steps = int(os.environ.get('DICE_WIZARD_STEPS', '8'))
    _step_settle = int(os.environ.get('DICE_STEP_SETTLE', '2'))

    def _real_confirmation(pg):
        """STRICT: only a genuine Dice post-submit confirmation counts (email is ground truth).
        Loose signals like bare 'applied'/'success' or a clicked button caused ~23 FALSE
        positives (logged 25, only 2 real emails). Require an explicit confirmation phrase or
        the /application-submitted URL."""
        try:
            body = (pg.locator('body').inner_text(timeout=2500) or '').lower()
            u = (pg.url or '').lower()
        except Exception:
            return False
        STRONG = ('application submitted', 'your application has been submitted',
                  'thank you for applying', "we've sent your application",
                  'application was sent', 'successfully submitted', 'application complete',
                  'you have successfully applied')
        if any(s in body for s in STRONG):
            return True
        if 'application-submitted' in u or 'applysuccess' in u or '/applied' in u:
            return True
        return False

    # multi-step easy-apply modal: fill questions + click Next/Submit up to N steps
    for _step in range(_wizard_steps):
        try:
            if is_questions_page and is_questions_page(page):
                fill_questions_page(page, None, {}, company or 'Employer')
        except Exception:
            pass
        if _real_confirmation(page):
            return 'submitted', company
        # login wall mid-wizard = NOT submitted (session lost)
        try:
            if 'login' in (page.url or '').lower() or 'sign in to continue' in \
                    (page.locator('body').inner_text(timeout=1500) or '').lower():
                return 'login_redirect', company
        except Exception:
            pass
        # click Next / Submit / Review
        advanced = False
        for sel in ['button:has-text("Submit")', 'button:has-text("Next")',
                    'button:has-text("Review")', 'button:has-text("Continue")']:
            try:
                loc = page.locator(sel)
                if loc.count() and loc.first.is_visible(timeout=1500):
                    loc.first.click(timeout=3000)
                    advanced = True
                    time.sleep(_step_settle)
                    break
            except Exception:
                continue
        if not advanced:
            break
    # final STRICT confirmation check — no click-only fallback (that caused false positives)
    if _real_confirmation(page):
        return 'submitted', company
    return 'incomplete', company


def main():
    headful = os.environ.get('HEADFUL', '0') == '1'
    target = int(os.environ.get('DICE_TARGET', '10'))
    db = get_db()
    init_db(db)
    _ = load_profile()

    applied_ids = _load_json_set(JK_FILE)
    failed_ids = _load_json_set(FAILED_FILE)
    dead = {k for k, c in _load_dead().items() if int(c) >= MAX_FAILS}
    applied_titles = _load_json_set(APPLIED_FILE)
    _apply_lessons_to_env()   # SELF-LEARNING: apply fixes learned from past failures
    print(f"🗂️  Dice dedup: {len(applied_ids)} ids applied, {len(applied_titles)} titles, "
          f"{len(dead)} retired")

    def _save_failed(jid):
        s = _load_json_set(FAILED_FILE); s.add(jid); _save_json_set(FAILED_FILE, s)
        d = _load_dead(); d[jid] = int(d.get(jid, 0)) + 1
        try:
            json.dump(d, open(DEAD_FILE, 'w'))
        except Exception:
            pass

    print(f"🚀 Dice apply — stealth={_STEALTH}, headful={headful}, target={target}")
    with sync_playwright() as pw:
        ctx = _launch(pw, headful)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # ── DYNAMIC LOGIN ───────────────────────────────────────────────────
        # The apply WIZARD needs a full authenticated session. Verify via /home-feed
        # (logged-out redirects to /dashboard/login). If logged out, AUTO-LOGIN with
        # DICE_EMAIL/DICE_PASSWORD (2-step). Manual window is the fallback.
        def _dice_logged_in():
            try:
                page.goto('https://www.dice.com/home-feed', wait_until='domcontentloaded', timeout=25000)
                time.sleep(3)
                return 'login' not in (page.url or '').lower()
            except Exception:
                return False

        def _try_google_login():
            """If Dice uses Google SSO, click 'Continue with Google'. Works when the Chrome
            profile is already signed into Google (bobrikh75@gmail.com)."""
            try:
                page.goto('https://www.dice.com/dashboard/login',
                          wait_until='domcontentloaded', timeout=30000)
                time.sleep(3)
                # find the Google button (text or aria-label or image alt)
                gbtn = None
                for sel in ('button:has-text("Google")', 'a:has-text("Google")',
                            '[aria-label*="Google" i]', 'button:has-text("Continue with Google")',
                            'button:has-text("Sign in with Google")', '[data-testid*="google" i]'):
                    try:
                        loc = page.locator(sel).first
                        if loc.count() > 0 and loc.is_visible():
                            gbtn = loc; break
                    except Exception:
                        continue
                if not gbtn:
                    print("  ℹ️ no 'Continue with Google' button found on login page")
                    return False
                print("  🔵 clicking 'Continue with Google'...")
                # Google SSO may open a popup or navigate in-page — handle both
                try:
                    with page.context.expect_page(timeout=8000) as pop:
                        gbtn.click()
                    popup = pop.value
                    time.sleep(4)
                    # if already signed into Google, click the account chooser tile
                    for sel in (f'[data-identifier="{os.environ.get("DICE_EMAIL","")}"]',
                                'div[role="link"]', '[data-authuser]'):
                        try:
                            t = popup.locator(sel).first
                            if t.count() > 0: t.click(); break
                        except Exception:
                            continue
                    time.sleep(6)
                except Exception:
                    # no popup — SSO navigated in same tab
                    time.sleep(6)
                    for sel in (f'[data-identifier="{os.environ.get("DICE_EMAIL","")}"]',
                                'div[role="link"]', '[data-authuser]'):
                        try:
                            t = page.locator(sel).first
                            if t.count() > 0: t.click(); break
                        except Exception:
                            continue
                    time.sleep(6)
                ok = _dice_logged_in()
                print(f"  {'✅' if ok else '❌'} Google login result: {page.url[:60]}")
                if not ok:
                    try: page.screenshot(path='data/dice_login_google.png')
                    except Exception: pass
                return ok
            except Exception as e:
                print(f"  ⚠️ google-login error: {str(e)[:100]}")
                return False

        def _auto_login():
            # Try Google SSO FIRST (Bob's Dice may be Google-linked → no password exists).
            if os.environ.get('DICE_LOGIN_METHOD', 'auto') in ('auto', 'google'):
                if _try_google_login():
                    return True
            email = os.environ.get('DICE_EMAIL', ''); pwd = os.environ.get('DICE_PASSWORD', '')
            if not email or not pwd:
                print("  ⚠️ no DICE_EMAIL/DICE_PASSWORD in env — cannot password-login")
                return False
            try:
                page.goto('https://www.dice.com/dashboard/login',
                          wait_until='domcontentloaded', timeout=30000)
                time.sleep(3)
                print(f"  🔐 login page: {page.url[:70]}")
                # captcha/challenge check (research: Dice-type sites block automated login)
                body = (page.content() or '').lower()
                for sig in ('captcha', 'recaptcha', 'are you a robot', 'verify you are human',
                            'unusual activity', 'px-captcha', 'perimeterx'):
                    if sig in body:
                        print(f"  🛑 login blocked by challenge: '{sig}' — automated login not possible here")
                        page.screenshot(path='data/dice_login_blocked.png')
                        return False
                # step 1: email — type like a human
                email_sel = 'input[name="email"], input[type="email"], input#email'
                page.wait_for_selector(email_sel, timeout=10000)
                page.click(email_sel); page.type(email_sel, email, delay=90)
                time.sleep(1)
                clicked = False
                for b in page.locator('button, [role="button"]').all():
                    try:
                        t = (b.inner_text() or '').lower()
                        if 'continue' in t or 'next' in t:
                            b.click(); clicked = True; break
                    except Exception:
                        continue
                if not clicked:
                    page.keyboard.press('Enter')
                time.sleep(3)
                print(f"  → after email step: {page.url[:70]}")
                # step 2: password — type like a human
                pwd_sel = 'input[name="password"], input[type="password"], input#password'
                page.wait_for_selector(pwd_sel, timeout=10000)
                page.click(pwd_sel); page.type(pwd_sel, pwd, delay=90)
                time.sleep(1)
                clicked = False
                for b in page.locator('button, [role="button"]').all():
                    try:
                        t = (b.inner_text() or '').strip().lower()
                        if t in ('sign in', 'log in', 'login', 'submit') or 'sign in' in t:
                            b.click(); clicked = True; break
                    except Exception:
                        continue
                if not clicked:
                    page.keyboard.press('Enter')
                time.sleep(6)
                print(f"  → after password step: {page.url[:70]}")
                ok = _dice_logged_in()
                if not ok:
                    try: page.screenshot(path='data/dice_login_failed.png')
                    except Exception: pass
                    print(f"  ❌ auto-login did not reach home-feed (lands on {page.url[:60]}) "
                          f"— check data/dice_login_failed.png artifact")
                return ok
            except Exception as e:
                print(f"  ⚠️ auto-login error: {str(e)[:120]}")
                try: page.screenshot(path='data/dice_login_error.png')
                except Exception: pass
                return False

        _logged = _dice_logged_in()
        if not _logged:
            print("  🔑 session logged out — attempting AUTO-LOGIN (DICE_EMAIL/DICE_PASSWORD)...")
            _logged = _auto_login()
            if _logged:
                print("  ✅ auto-login succeeded (session at /home-feed)")
                try:
                    os.makedirs('data', exist_ok=True)
                    json.dump(ctx.cookies(), open(COOKIE_FILE, 'w'))
                except Exception:
                    pass
        if not _logged and os.environ.get('DICE_MANUAL_LOGIN') == '1':
            try:
                page.goto('https://www.dice.com/dashboard/login', wait_until='domcontentloaded', timeout=30000)
            except Exception:
                pass
            print("  👤 MANUAL LOGIN fallback: log into Dice in the Chrome window (up to 180s)...")
            for _ in range(60):
                time.sleep(3)
                if _dice_logged_in():
                    _logged = True
                    try:
                        json.dump(ctx.cookies(), open(COOKIE_FILE, 'w'))
                    except Exception:
                        pass
                    print("     🍪 login detected + saved")
                    break
        if not _logged:
            print("  ⛔ NOT logged into Dice (no creds / login failed) — applies will login_redirect. "
                  "Set DICE_EMAIL+DICE_PASSWORD in agent/.env, or run DICE_MANUAL_LOGIN=1 and log in.")

        # CV-matched query pool (Java/Spring/backend/remote — all close to Bob's CV).
        # Includes Dice BOOLEAN queries (AND/OR/NOT) for precise CV targeting — Dice supports
        # boolean operators in q= (verified via Dice career-advice boolean-search docs).
        _custom = os.environ.get('DICE_TERM', '').strip()
        _pool = ['Java backend developer', 'Java microservices',
                 'Senior Java developer', 'Java developer remote',
                 'Java AWS developer', 'Spring Boot microservices',
                 'Java REST API developer', 'Java software engineer',
                 'Core Java developer', 'Java full stack developer',
                 'Java Kafka developer', 'Java Spring Cloud', 'Java backend engineer',
                 'Lead Java developer', 'Java API developer', 'Spring Boot engineer',
                 # Boolean: precise CV match, exclude off-CV noise (.NET/Azure architect/test)
                 'Java AND (Spring OR "Spring Boot") NOT .NET',
                 'Java AND (Kafka OR microservices) AND (AWS OR Kubernetes) NOT Azure',
                 '(Java OR "Core Java") AND (backend OR "REST API") NOT (test OR QA)',
                 'Java Kubernetes microservices', 'Java Spring developer', 'backend Java engineer']
        # rotate the pool start each run (persist cursor) so runs cover DIFFERENT queries first
        _cur_file = 'data/dice_query_cursor.json'
        try:
            _cur = json.load(open(_cur_file)).get('i', 0)
        except Exception:
            _cur = 0
        _pool = _pool[_cur % len(_pool):] + _pool[:_cur % len(_pool)]
        try:
            os.makedirs('data', exist_ok=True)
            json.dump({'i': (_cur + 3) % 22}, open(_cur_file, 'w'))
        except Exception:
            pass
        # custom term (dispatch input) always leads if provided; else default Java Spring Boot
        terms = ([_custom] if _custom else ['Java Spring Boot']) + _pool
        _pages = int(os.environ.get('DICE_SEARCH_PAGES', '3'))
        jobs = []
        seen = set()
        for term in terms:
            for url, title in _search_urls(page, term, pages=_pages):
                jid = _job_id(url)
                if jid and jid not in seen:
                    seen.add(jid)
                    jobs.append((url, title, jid))
            # collect a big pool (deeper coverage) — stop only when we have plenty
            if len(jobs) >= max(300, target * 12):
                break
        print(f"🔍 {len(jobs)} unique Dice easy-apply jobs found")

        submitted = 0
        _seen_titles = set()
        _login_redirect_seen = False
        for url, title, jid in jobs:
            if submitted >= target:
                break
            # ---- 5-layer dedup, all BEFORE opening ----
            if jid and jid in dead:
                continue
            if jid and jid in applied_ids:
                print(f"  ⏭️ already applied (id={jid[:8]}) — skip"); continue
            if jid and jid in failed_ids and os.environ.get('RETRY_FAILED') != '1':
                print(f"  ⏭️ previously failed (id={jid[:8]}) — skip"); continue
            nt = _title_key('', title)
            if nt and (nt in applied_titles or nt in _seen_titles):
                print(f"  ⏭️ dup/applied title — skip: {title[:40]}"); continue
            # ---- CV-fit gate ----
            if should_apply and os.environ.get('CV_MATCH_OFF') != '1':
                ok, score, why = should_apply(title, '', 'Remote')
                if not ok:
                    # Generic-title SOFT reject (score >= -5, e.g. "Software Engineer"): the TITLE
                    # lacks a Java signal but the DESCRIPTION might have it. Open the job and
                    # re-check with the real description before skipping — recovers Java jobs
                    # hidden behind generic titles. Hard negatives (.NET/Python/C++, score<=-10)
                    # skip fast (no wasted page open).
                    if score is not None and score >= -5 and os.environ.get('DICE_DEEP_CV', '1') == '1':
                        try:
                            page.goto(url, wait_until='domcontentloaded', timeout=25000)
                            time.sleep(2)
                            desc = page.evaluate(
                                "() => (document.querySelector('[data-testid=\"jobDescriptionHtml\"]')"
                                " || document.body).innerText || ''")[:4000]
                            ok2, score2, why2 = should_apply(title, desc, 'Remote')
                            if ok2:
                                print(f"  ✅ recovered via description: '{title[:40]}' (score={score2})")
                                ok, score, why = ok2, score2, why2
                            else:
                                print(f"  ⏭️ off-CV (desc-checked): '{title[:40]}' (score={score2})")
                                continue
                        except Exception:
                            print(f"  ⏭️ off-CV: '{title[:40]}' (score={score}, desc check failed)")
                            continue
                    else:
                        print(f"  ⏭️ off-CV: '{title[:40]}' (score={score} {','.join(why)})")
                        continue
            # ---- DB atomic claim (concurrent-safe) ----
            if not claim_job(db, 'dice:' + (title or ''), title):
                print(f"  🔒 claimed by another run — skip: {title[:35]}"); continue

            print(f"  ▶ applying: {title[:50]}")
            try:
                result, company = _apply_one(page, url, title)
            except Exception as e:
                result, company = 'error', ''
                print(f"    ERR {str(e)[:70]}")
            if result == 'submitted':
                submitted += 1
                applied_ids.add(jid); _save_json_set(JK_FILE, applied_ids)
                if nt:
                    applied_titles.add(nt); _save_json_set(APPLIED_FILE, applied_titles); _seen_titles.add(nt)
                try:
                    upsert_application(db, company=company or 'Dice Employer', job_title=title or 'Dice Job',
                                       job_url=url, ats_type='dice', status='applied', match_score=75)
                except Exception:
                    pass
                print(f"  ✅ SUBMITTED #{submitted}: {title[:45]} @ {company[:20]}")
            elif result == 'already_applied':
                # Dice's own "Applied" state → add to dedup so we never re-open it, no fail count
                release_claim(db, 'dice:' + (title or ''), title)
                if jid:
                    applied_ids.add(jid); _save_json_set(JK_FILE, applied_ids)
                if nt:
                    applied_titles.add(nt); _save_json_set(APPLIED_FILE, applied_titles); _seen_titles.add(nt)
            else:
                release_claim(db, 'dice:' + (title or ''), title)   # not applied → free claim
                if jid:
                    _save_failed(jid)
                _record_dice_lesson(result)   # SELF-LEARNING: next run auto-applies the fix
                if result == 'login_redirect':
                    _login_redirect_seen = True
                print(f"  -> {result}: {title[:40]}")
            time.sleep(2)

        # Save FRESH cookies after the run — browsing refreshes the session, so this keeps
        # the DICE_COOKIES refresh source (dice_cookies.json) as new as possible. Dynamic:
        # the refresh workflow reads this on its schedule, so the secret stays valid.
        try:
            os.makedirs('data', exist_ok=True)
            json.dump(ctx.cookies(), open(COOKIE_FILE, 'w'))
        except Exception:
            pass
        # If the session had expired mid-run (login_redirect), flag it so the cookie-refresh
        # workflow / next run knows to re-authenticate — no manual step needed.
        if _login_redirect_seen:
            try:
                json.dump({'ts': time.time(), 'reason': 'login_redirect'},
                          open('data/dice_needs_login.json', 'w'))
            except Exception:
                pass
            print("  ⚠️ SESSION EXPIRED (login_redirect) — DICE_COOKIES needs refresh. The "
                  "refresh-dice-cookies workflow will update it; or run DICE_MANUAL_LOGIN=1 locally.")

        print(f"\n=== Dice: SUBMITTED {submitted} application(s) ===")
        ctx.close()


if __name__ == '__main__':
    main()
