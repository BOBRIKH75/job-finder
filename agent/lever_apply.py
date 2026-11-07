#!/usr/bin/env python3
"""Lever direct-apply (browser) for CV-fit Java/backend jobs.

Flow: Lever public postings API (companies.json 'lever' list, rotated each run) -> CV-fit
gate (cv_match) -> fresh only -> dedup (30d TTL) -> open <posting>/apply in real Chrome
(patchright, headful) -> fill the standard fields from config/profile.json ONLY -> upload CV
-> answer custom questions via questions_filler (profile/memory based, never invented)
-> Submit. 'submitted' ONLY when Lever lands on its /thanks page (post-submit signal).
hCaptcha challenge = skipped (no solver spend); logged as 'captcha'.

Safe caps: LEVER_TARGET per run (default 8), 25-60s jitter between applies.
"""
import json
import os
import random
import re
import sys
import time

sys.path.insert(0, '.')
sys.path.insert(0, 'src')

try:
    from patchright.sync_api import sync_playwright
    _STEALTH = 'patchright'
except Exception:
    from playwright.sync_api import sync_playwright
    _STEALTH = 'playwright'

import httpx
from src.form_filler import load_profile
from src.memory import get_db, init_db
from src.portal_scanner import load_companies, matches_skills, is_disqualified, _is_fresh
try:
    from src.cv_match import should_apply
except Exception:
    should_apply = None
try:
    from src.questions_filler import fill_questions_page
except Exception:
    fill_questions_page = None

APPLIED_FILE = 'data/lever_applied.json'
FAILED_FILE = 'data/lever_failed.json'
STATS_FILE = 'data/lever_stats.json'
CURSOR_FILE = 'data/lever_cursor.json'
TTL_DAYS = int(os.environ.get('LEVER_TTL_DAYS', '30'))
FAIL_TTL_DAYS = int(os.environ.get('LEVER_FAIL_TTL_DAYS', '3'))
TARGET = int(os.environ.get('LEVER_TARGET', '8'))
COMPANIES_PER_RUN = int(os.environ.get('LEVER_COMPANIES', '40'))


def _jload(p, d):
    try:
        return json.load(open(p))
    except Exception:
        return d


def _jsave(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(o, open(p, 'w'), indent=0)


def _fresh_keys(path, ttl_days):
    raw = _jload(path, {})
    now = time.time()
    return {k for k, ts in raw.items() if now - float(ts) < ttl_days * 86400} if isinstance(raw, dict) else set()


def _mark(path, key):
    raw = _jload(path, {})
    raw = raw if isinstance(raw, dict) else {}
    raw[key] = time.time()
    cutoff = time.time() - 90 * 86400
    _jsave(path, {k: v for k, v in raw.items() if v > cutoff})


def _stat(field):
    st = _jload(STATS_FILE, {})
    d = st.setdefault(time.strftime('%Y-%m-%d'), {'attempted': 0, 'submitted': 0, 'captcha': 0, 'other': 0})
    d[field] = d.get(field, 0) + 1
    _jsave(STATS_FILE, st)


def gather_jobs():
    companies = (load_companies() or {}).get('lever', [])
    cur = int(_jload(CURSOR_FILE, {}).get('i', 0)) % max(len(companies), 1)
    batch = (companies[cur:] + companies[:cur])[:COMPANIES_PER_RUN]
    _jsave(CURSOR_FILE, {'i': (cur + COMPANIES_PER_RUN) % max(len(companies), 1)})
    jobs = []
    for co in batch:
        try:
            r = httpx.get(f'https://api.lever.co/v0/postings/{co}?mode=json', timeout=12)
            if r.status_code != 200:
                continue
            for p in r.json():
                title = p.get('text', '')
                desc = p.get('descriptionPlain', '') or ''
                loc = (p.get('categories') or {}).get('location', '') or ''
                if not _is_fresh(p.get('createdAt'), 30):
                    continue
                if not matches_skills(title, desc) or is_disqualified(title, desc):
                    continue
                if should_apply and os.environ.get('CV_MATCH_OFF') != '1':
                    ok, score, why = should_apply(title, desc[:4000], loc or 'Remote')
                    if not ok:
                        continue
                url = p.get('hostedUrl') or ''
                m = re.search(r'lever\.co/([^/]+)/([0-9a-f-]{20,})', url)
                if m:
                    jobs.append({'co': co, 'id': m.group(2), 'title': title, 'loc': loc,
                                 'url': f'https://jobs.lever.co/{m.group(1)}/{m.group(2)}/apply'})
        except Exception:
            continue
    random.shuffle(jobs)
    return jobs


def _fill_basic(page, profile):
    first = profile.get('first_name', '')
    last = profile.get('last_name', '')
    vals = {
        'name': f'{first} {last}'.strip(),
        'email': profile.get('email', ''),
        'phone': profile.get('phone', ''),
        'urls[LinkedIn]': profile.get('linkedin', ''),
        'urls[GitHub]': profile.get('github', ''),
    }
    for name, v in vals.items():
        if not v:
            continue
        try:
            loc = page.locator(f'input[name="{name}"]')
            if loc.count():
                loc.first.fill(v, timeout=3000)
        except Exception:
            pass
    # location (autocomplete) - optional, type city only
    try:
        loc = page.locator('input[name="location"]')
        if loc.count() and loc.first.is_visible():
            loc.first.fill(profile.get('city') and f"{profile['city']}, {profile.get('state', '')}" or '', timeout=3000)
            time.sleep(1.5)
            opt = page.locator('.dropdown-results div, .dropdown-container [role=option]')
            if opt.count():
                opt.first.click(timeout=2000)
    except Exception:
        pass
    # resume
    resume = profile.get('resume_path') or 'resume.pdf'
    for cand in (resume, os.path.join('agent', resume), os.path.join('..', resume), 'resume.pdf'):
        if os.path.exists(cand):
            try:
                page.locator('input[type=file][name=resume], input#resume-upload-input').first.set_input_files(
                    os.path.abspath(cand), timeout=8000)
                time.sleep(4)
            except Exception:
                pass
            break


def _body(page):
    try:
        return (page.locator('body').inner_text(timeout=3000) or '').lower()
    except Exception:
        return ''


def apply_one(page, job, profile, db):
    page.goto(job['url'], wait_until='domcontentloaded', timeout=30000)
    time.sleep(3)
    b = _body(page)
    if 'no longer' in b or 'page not found' in b or '404' in (page.title() or ''):
        return 'closed'
    if not page.locator('input[name="email"]').count():
        return 'no_form'
    _fill_basic(page, profile)
    if fill_questions_page:
        try:
            fill_questions_page(page, db, profile, job['co'])
        except Exception:
            pass
    # EEO / optional selects are left default; required custom selects handled by filler
    btn = page.locator('button#btn-submit, button[type=submit]:has-text("Submit")')
    if not btn.count():
        return 'no_submit'
    btn.first.scroll_into_view_if_needed(timeout=3000)
    btn.first.click(timeout=5000)
    for _ in range(12):
        time.sleep(2.5)
        u = (page.url or '').lower()
        b = _body(page)
        if '/thanks' in u or 'application submitted' in b or 'thanks for applying' in b \
                or 'application has been received' in b or 'we have received your application' in b:
            return 'submitted'
        if 'hcaptcha' in b and ('verify' in b or 'challenge' in b) or \
                page.locator('iframe[src*="hcaptcha.com/captcha"][style*="visible"]').count():
            return 'captcha'
    errs = page.locator('.error-message, .application-error, [class*=error]:visible').all_inner_texts()
    print(f"    form errors: {[e[:60] for e in errs[:3]]}")
    return 'incomplete'


def verify_gmail():
    """Count Lever confirmation emails (from hire.lever.co) in the last 2 days - truthful check."""
    import imaplib, email as _em
    from datetime import datetime, timedelta, timezone
    u, pw = os.environ.get('GMAIL_USER', ''), os.environ.get('GMAIL_APP_PASSWORD', '')
    if not u or not pw:
        return
    try:
        M = imaplib.IMAP4_SSL('imap.gmail.com'); M.login(u, pw); M.select('inbox')
        since = (datetime.now(timezone.utc) - timedelta(days=2)).strftime('%d-%b-%Y')
        typ, d = M.search(None, f'(FROM "lever.co" SINCE {since})')
        ids = d[0].split()
        subs = []
        for i in ids[-40:]:
            typ, md = M.fetch(i, '(BODY.PEEK[HEADER.FIELDS (SUBJECT)])')
            subs.append(' '.join(_em.message_from_bytes(md[0][1]).get('Subject', '').split())[:70])
        M.logout()
        conf = [x for x in subs if re.search(r'thank|appl', x, re.I)]
        print(f"📧 Gmail: {len(ids)} Lever emails in 2d, {len(conf)} look like application confirmations")
        for x in conf[-10:]:
            print("   •", x)
    except Exception as e:
        print(f"  (gmail verify skipped: {str(e)[:60]})")


def main():
    profile = load_profile()
    db = get_db()
    init_db(db)
    applied = _fresh_keys(APPLIED_FILE, TTL_DAYS)
    failed = _fresh_keys(FAILED_FILE, FAIL_TTL_DAYS)
    jobs = [j for j in gather_jobs() if j['id'] not in applied and j['id'] not in failed]
    print(f"🔍 Lever: {len(jobs)} CV-fit fresh jobs (target {TARGET}, stealth={_STEALTH})")
    if not jobs:
        return
    profile_dir = os.path.join(os.path.expanduser('~'), '.lever-profile')
    try:
        import pwd
        profile_dir = os.path.join(pwd.getpwuid(os.getuid()).pw_dir, '.lever-profile')
    except Exception:
        pass
    done = 0
    with sync_playwright() as pw:
        kw = dict(user_data_dir=profile_dir, headless=os.environ.get('HEADFUL', '1') != '1', no_viewport=True)
        if _STEALTH == 'patchright':
            kw['channel'] = 'chrome'
        try:
            ctx = pw.chromium.launch_persistent_context(**kw)
        except Exception:
            kw.pop('channel', None)
            ctx = pw.chromium.launch_persistent_context(**kw)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for job in jobs:
            if done >= TARGET:
                break
            print(f"  ▶ {job['co']}: {job['title'][:55]}")
            _stat('attempted')
            try:
                res = apply_one(page, job, profile, db)
            except Exception as e:
                res = 'error'
                print(f"    ERR {str(e)[:70]}")
            if res == 'submitted':
                done += 1
                _mark(APPLIED_FILE, job['id'])
                _stat('submitted')
                print(f"  ✅ SUBMITTED #{done}: {job['title'][:45]} @ {job['co']}")
            else:
                _mark(FAILED_FILE, job['id'])
                _stat('captcha' if res == 'captcha' else 'other')
                print(f"  -> {res}")
            time.sleep(random.uniform(25, 60))   # jitter between applies (account-safety)
        ctx.close()
    print(f"\n=== Lever: SUBMITTED {done} application(s) (post-submit /thanks signal) ===")
    time.sleep(60)
    verify_gmail()


if __name__ == '__main__':
    main()
