#!/usr/bin/env python3
"""REAL step-by-step submitter for ONE Indeed SmartApply job.

Follows Bobur's EXACT taught loop — NO skipping:
  1. open the job page
  2. reload up to 3 times, screenshot each reload (confirm it loaded)
  3. click "Apply with Indeed"
  4. on redirect -> screenshot
  5. BEFORE finding Continue: scroll top/mid/bottom, screenshot each (see WHOLE page)
  6. find the VISIBLE Continue -> click it
  7. wait -> screenshot -> learn the page
  8. if it is a questions page -> FILL every required field first
  9. loop 5-8 for every next page
 10. at the FINAL "Submit your application" -> CLICK Submit (this is REAL)
 11. wait -> screenshot the confirmation ("thank you") page

Screenshots go to screenshots/, 1000px wide (readable), named by step.
Headed. Submits exactly ONE application, then stops.
"""
import json
import os
import random
import sqlite3
import sys
import time

sys.path.insert(0, '.')
sys.path.insert(0, 'src')


def _load_env():
    """Load agent/.env into os.environ (local). In CI/CD, secrets are already
    injected as env vars, so we only set keys that aren't already present."""
    for path in ('.env', 'agent/.env'):
        try:
            for line in open(path):
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            break
        except Exception:
            continue


_load_env()

# Patchright = stealth-patched Playwright that passes Cloudflare Turnstile naturally
# (2026 best practice). Drop-in: same API. Falls back to plain Playwright if absent.
try:
    from patchright.sync_api import sync_playwright
    _STEALTH = 'patchright'
except Exception:
    from playwright.sync_api import sync_playwright
    _STEALTH = 'playwright'
from memory import init_db, application_exists, upsert_application
from questions_filler import is_questions_page, fill_questions_page

# Bobur's existing auto-captcha solver chain (NopeCHA -> audio -> Gemini -> hCaptcha token
# -> reCAPTCHA Enterprise). Try these FIRST; human handoff is the last resort.
try:
    from applier import _try_auto_captcha_solve
except Exception:
    try:
        from src.applier import _try_auto_captcha_solve
    except Exception:
        _try_auto_captcha_solve = None

SHOT_DIR = 'screenshots'
MAX_STEPS = 20


def load_cookies():
    c = json.load(open('data/indeed_cookies.json'))
    for x in c:
        x['secure'] = bool(x.get('secure', False))
        if x.get('sameSite') not in ('Strict', 'Lax', 'None'):
            x['sameSite'] = 'Lax'
    return c


def snap(page, tag):
    os.makedirs(SHOT_DIR, exist_ok=True)
    ts = time.strftime('%H%M%S')
    path = f"{SHOT_DIR}/submit_{ts}_{tag}.png"
    try:
        page.screenshot(path=path, full_page=False)
        print(f"    📸 {path}")
    except Exception as e:
        print(f"    shot fail {tag}: {str(e)[:50]}")
    return path


def scroll_and_snap(page, tag):
    """Scroll top -> mid -> bottom, screenshot each; return to top."""
    for name, frac in [('top', 0.0), ('mid', 0.5), ('bot', 1.0)]:
        try:
            page.evaluate(f"() => window.scrollTo(0, document.body.scrollHeight * {frac})")
        except Exception:
            pass
        time.sleep(1.0)
        snap(page, f"{tag}_{name}")
    try:
        page.evaluate("() => window.scrollTo(0, 0)")
    except Exception:
        pass
    time.sleep(0.5)


def is_cloudflare(page):
    try:
        if '__cf_chl' in (page.url or ''):
            return True
        b = page.locator('body').inner_text(timeout=2000).lower()
        return ('verify you are human' in b or 'additional verification' in b
                or 'checking your browser' in b)
    except Exception:
        return False


def pct(page):
    try:
        lines = [l.strip() for l in page.locator('body').inner_text(timeout=3000).split('\n')]
        return next((l for l in lines if l.endswith('%') and l[:-1].isdigit()), '?')
    except Exception:
        return '?'


def heading(page):
    try:
        lines = [l.strip() for l in page.locator('body').inner_text(timeout=3000).split('\n') if l.strip()]
        return lines[:4]
    except Exception:
        return []


def has_submit(page):
    try:
        return page.locator(
            '[data-testid="submit-application-button"], '
            'button:has-text("Submit your application")').count() > 0
    except Exception:
        return False


def _find_submit(page):
    selectors = ['[data-testid="submit-application-button"]',
                 'button:has-text("Submit your application")',
                 'button:has-text("Submit application")',
                 'button:has-text("Submit")']
    for sel in selectors:
        loc = page.locator(sel)
        for i in range(min(loc.count(), 6)):
            el = loc.nth(i)
            try:
                if el.is_visible(timeout=1200):
                    return el
            except Exception:
                continue
    return None


def click_submit(page):
    """Click Submit and VERIFY it REALLY submitted. Returns True ONLY when a real
    confirmation is reached (post-apply URL or 'application submitted' text).
    A mere page change is NOT enough — it may just navigate elsewhere."""
    for attempt in range(4):
        try:
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
        time.sleep(1.2)
        el = _find_submit(page)
        if el is None:
            # no submit button -> only success if a real confirmation is present
            if is_confirmation(page):
                print(f"      ✔ submit verified via confirmation (attempt {attempt+1})")
                return True
            time.sleep(1)
            continue
        strategies = [
            lambda e: (e.scroll_into_view_if_needed(timeout=2500), e.click(timeout=4000)),
            lambda e: e.click(timeout=4000, force=True),
            lambda e: e.dispatch_event('click'),
            lambda e: e.evaluate("(b) => b.click()"),
        ]
        for strat in strategies:
            try:
                strat(el)
            except Exception:
                continue
            time.sleep(3)
            try:
                page.wait_for_load_state('domcontentloaded', timeout=6000)
            except Exception:
                pass
            # ONLY a real confirmation counts as success.
            if is_confirmation(page):
                print(f"      ✔ submit verified via confirmation (attempt {attempt+1})")
                return True
        time.sleep(1)
    return False


def click_continue(page):
    # The Continue button can be BELOW the fold (after EEO fields + consent toggles).
    # Scroll to the bottom first so it becomes reachable, then click (with JS fallback).
    try:
        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    except Exception:
        pass
    time.sleep(0.8)
    # The advance button varies by page: 'Continue' on most, but 'Review your
    # application' on the demographic/EEO page (LEARNED from Bobur screenshots 2026-09-01).
    # Use PRECISE matches only — loose 'Review'/'Next' caused repeated mis-clicks/looping.
    for sel in ['[data-testid="continue-button"]',
                'button:has-text("Review your application")',
                'button:has-text("Continue")']:
        loc = page.locator(sel)
        for i in range(min(loc.count(), 8)):
            el = loc.nth(i)
            try:
                if el.is_visible(timeout=1200):
                    el.scroll_into_view_if_needed(timeout=2000)
                    try:
                        el.click(timeout=4000)
                    except Exception:
                        try:
                            el.click(timeout=3000, force=True)
                        except Exception:
                            el.evaluate("(b) => b.click()")
                    return True
            except Exception:
                continue
    return False


def is_confirmation(page):
    # URL-based signal is the most reliable post-submit indicator.
    try:
        u = (page.url or '').lower()
        if 'post-apply' in u or 'confirmation' in u or 'applied' in u or 'appliedconfirmation' in u:
            return 'url:' + u.split('/')[-1][:24]
    except Exception:
        pass
    try:
        b = page.locator('body').inner_text(timeout=3000).lower()
    except Exception:
        b = ''
    # STRONG phrases only — these appear ONLY after a real submit.
    # NOTE: 'get email updates' / 'tell us a bit' also appear on the REVIEW page,
    # so they are NOT reliable and are intentionally excluded (false-positive fix).
    for phrase in ['your application has been submitted', 'application submitted',
                   'thank you for applying', 'we sent your application',
                   'application was submitted', 'has been submitted to']:
        if phrase in b:
            return phrase
    return None


def _has_indeed_error(page):
    """Detect the SmartApply 'Something went wrong / please try again later' error dialog."""
    try:
        b = page.locator('body').inner_text(timeout=2000).lower()
    except Exception:
        return False
    return ('something went wrong' in b and 'try again' in b) or \
           'our system is having some trouble' in b


def has_recaptcha(page):
    """Detect a reCAPTCHA/'not a robot' challenge that needs a human to solve."""
    try:
        if page.locator('iframe[src*="recaptcha"], iframe[title*="recaptcha" i], '
                        'iframe[src*="hcaptcha"], iframe[title*="challenge" i], '
                        '#recaptcha-anchor, .g-recaptcha, [data-testid*="captcha" i]').count() > 0:
            for sel in ['iframe[src*="recaptcha"]', 'iframe[src*="hcaptcha"]', '.g-recaptcha']:
                loc = page.locator(sel)
                for i in range(min(loc.count(), 4)):
                    try:
                        if loc.nth(i).is_visible(timeout=800):
                            return True
                    except Exception:
                        continue
    except Exception:
        pass
    return False


def wait_for_human_captcha(page, max_wait=180):
    """Try Bobur's auto-solver chain first; reload to clear; human handoff last."""
    if not has_recaptcha(page):
        return True

    # 1) Try the existing auto-solver chain (NopeCHA/audio/Gemini/hCaptcha/enterprise).
    if _try_auto_captcha_solve is not None:
        try:
            print("   🔓 trying auto-captcha solver chain...")
            if _try_auto_captcha_solve(page) and not has_recaptcha(page):
                print("   ✅ auto-solver cleared the CAPTCHA")
                snap(page, "CAPTCHA_autosolved")
                return True
        except Exception as _e:
            print(f"   ⚠️ auto-solver error: {str(_e)[:60]}")

    # 2) Reload to clear (LEARNED: reloading often removes the checkbox).
    for rl in range(2):
        if has_recaptcha(page):
            print(f"   🔄 reloading to clear CAPTCHA ({rl+1}/2)")
            try:
                page.reload(wait_until='domcontentloaded', timeout=20000)
            except Exception:
                pass
            time.sleep(4)
        else:
            print("   ✅ CAPTCHA cleared after reload")
            return True

    if not has_recaptcha(page):
        return True

    # 3) Human handoff (last resort — a bot must not auto-solve Google image grids).
    snap(page, "CAPTCHA_needs_human")
    print("\n" + "=" * 60)
    print("🤖➡️🧑  reCAPTCHA / 'I'm not a robot' — auto-solve failed.")
    print("   PLEASE solve it manually in the browser window now.")
    print(f"   Waiting up to {max_wait}s for you to finish...")
    print("=" * 60)
    try:
        os.system('afplay /System/Library/Sounds/Glass.aiff >/dev/null 2>&1 &')
    except Exception:
        pass
    waited = 0
    while waited < max_wait:
        time.sleep(3)
        waited += 3
        if not has_recaptcha(page):
            print(f"   ✅ CAPTCHA cleared after ~{waited}s — continuing.")
            snap(page, "CAPTCHA_cleared")
            return True
    print("   ⚠️ CAPTCHA still present after wait — continuing anyway (submit may fail).")
    return False


# --- Self-healing flow: learn from failures, apply fixes next time ---
LESSONS_FILE = 'data/flow_lessons.json'


def load_lessons():
    """Return dict of learned adjustments, e.g. {'stuck_pct_88': {'count': 3, 'fix': 'extra_reload'}}."""
    try:
        return json.load(open(LESSONS_FILE))
    except Exception:
        return {}


def record_lesson(reason, step, pct, detail=''):
    """Record a failure pattern + the fix to apply next time. Dynamic + persistent."""
    lessons = load_lessons()
    # Key the lesson by the failure signature (reason + where it happened).
    key = f"{reason}@pct{pct}"
    entry = lessons.get(key, {'count': 0, 'fix': None, 'detail': detail})
    entry['count'] += 1
    entry['detail'] = detail or entry.get('detail', '')
    # Decide the fix to try next time based on the failure type.
    if reason == 'stuck':
        # stuck after filling -> next time do extra reload + longer settle
        entry['fix'] = 'extra_reload_and_wait'
    elif reason == 'submit_click_failed':
        # submit didn't land -> next time poll submit longer + JS click first
        entry['fix'] = 'longer_submit_poll'
    elif reason == 'error':
        entry['fix'] = 'reload_and_retry'
    lessons[key] = entry
    try:
        os.makedirs('data', exist_ok=True)
        json.dump(lessons, open(LESSONS_FILE, 'w'), indent=2)
        print(f"  🧠 learned: {key} -> fix='{entry['fix']}' (seen {entry['count']}x)")
    except Exception:
        pass


def submit_one(pg, url, db, profile):
    print(f"\n===== SUBMIT ONE: {url[-40:]}")

    # STEP 1-2: open + reload up to 3 times, screenshot each
    pg.goto(url, wait_until='domcontentloaded', timeout=25000)
    time.sleep(3)
    for r in range(3):
        snap(pg, f"open_reload{r}")
        if is_cloudflare(pg):
            print(f"  reload {r}: still Cloudflare — reloading")
        else:
            print(f"  reload {r}: loaded (url ...{pg.url[-30:]})")
            break
        if r < 2:
            try:
                pg.reload(wait_until='domcontentloaded', timeout=25000)
            except Exception:
                pass
            time.sleep(3)
    if is_cloudflare(pg):
        print("  STILL Cloudflare after 3 reloads — cannot proceed on this job")
        snap(pg, "SKIP_cloudflare")
        return 'cloudflare_stuck'

    # Skip jobs already CONFIRMED via email OR previously submitted by title
    # (Indeed re-posts the same role under a NEW link — skip by title, not just jk).
    try:
        import json as _json, re as _re
        def _norm(s):
            return _squash(_re.sub(r'[^a-z0-9 ]', ' ', (s or '').lower()))
        def _squash(s):
            return _re.sub(r'\s+', ' ', s or '').strip()
        confirmed = set()
        for f in ('data/email_confirmed_titles.json', 'data/applied_titles.json'):
            try:
                confirmed.update(_json.load(open(f)))
            except Exception:
                pass
        # Get the REAL job title from the job-title heading, NOT nav chrome.
        real_title = ''
        try:
            real_title = pg.evaluate(
                """() => {
                    const el = document.querySelector('h1, h2, [data-testid*="jobTitle" i], .jobsearch-JobInfoHeader-title');
                    return el ? el.textContent.trim() : '';
                }""") or ''
        except Exception:
            real_title = ''
        rt = _norm(real_title)
        # Require a strong, specific match (>= 15 chars) against the real title only.
        if rt and len(rt) > 8:
            for ct in confirmed:
                core = _norm(ct)
                if core and len(core) >= 15 and (core in rt or rt in core):
                    print(f"  ⏭️  already applied/confirmed by title — skipping ({real_title[:40]})")
                    snap(pg, "SKIP_title_confirmed")
                    return 'email_confirmed_skip'
    except Exception:
        pass

    # Capture the real job title now (job page) for later save-on-submit.
    job_title = ''
    try:
        job_title = pg.evaluate(
            """() => {
                const el = document.querySelector('h1, h2, [data-testid*="jobTitle" i], .jobsearch-JobInfoHeader-title');
                return el ? el.textContent.trim() : '';
            }""") or ''
    except Exception:
        job_title = ''

    # Already applied? The greyed "Applied" button is the RELIABLE signal
    # (Bobur screenshot: KeyData Cyber showed 'Applied'). Detect it, record the jk
    # so this job is NEVER opened again, and skip.
    try:
        applied_btn = pg.locator('button:has-text("Applied"), [role="button"]:has-text("Applied")')
        for i in range(min(applied_btn.count(), 5)):
            b = applied_btn.nth(i)
            try:
                if b.is_visible(timeout=800):
                    txt = (b.inner_text(timeout=800) or '').strip().lower()
                    if txt == 'applied' or (txt.startswith('applied') and 'apply' not in txt):
                        print("  ⏭️  'Applied' button present — already applied, recording + skipping")
                        snap(pg, "SKIP_applied_button")
                        # record jk so the main loop never opens it again
                        try:
                            import re as _re, json as _json
                            m = _re.search(r'jk=([0-9a-f]+)', url or '')
                            if m:
                                jkf = 'data/applied_jks.json'
                                try:
                                    s = set(_json.load(open(jkf)))
                                except Exception:
                                    s = set()
                                s.add(m.group(1))
                                _json.dump(sorted(s), open(jkf, 'w'))
                        except Exception:
                            pass
                        return 'already_applied'
            except Exception:
                continue
    except Exception:
        pass

    # STEP 3: click Apply with Indeed
    ab = pg.locator('button:has-text("Apply with Indeed"), span:has-text("Apply with Indeed")')
    if ab.count() == 0:
        print("  no 'Apply with Indeed' button on this job")
        snap(pg, "SKIP_no_apply_button")
        return 'no_apply_button'
    print("  clicking 'Apply with Indeed'...")
    # Overlay-proof click: a popup div can intercept pointer events. Try normal,
    # then force, then JS click so it never throws and crashes the job.
    try:
        ab.first.click(timeout=4000)
    except Exception:
        try:
            ab.first.click(timeout=3000, force=True)
        except Exception:
            try:
                ab.first.evaluate("(b) => b.click()")
            except Exception as _e:
                print(f"  ⚠️ Apply click failed: {str(_e)[:50]}")
                snap(pg, "SKIP_apply_click_failed")
                return 'no_apply_button'
    time.sleep(5)

    # STEP 4: screenshot after redirect
    snap(pg, "after_apply_click")

    # STEP 5-10: loop each page
    for step in range(MAX_STEPS):
        # LEARNED (Bobur screenshot 2026-09-01): SmartApply sometimes throws
        # "Something went wrong — please try again later" (a SERVER error, often from
        # automated/too-fast interaction). Dismiss it (OK) and RELOAD to recover.
        for er in range(3):
            if _has_indeed_error(pg):
                print(f"  STEP{step}: 'Something went wrong' dialog — OK + reload ({er+1}/3)")
                snap(pg, f"step{step}_indeed_error{er}")
                try:
                    ok = pg.get_by_role("button", name="OK")
                    if ok.count() and ok.first.is_visible(timeout=1500):
                        ok.first.click(timeout=2500)
                        time.sleep(1)
                except Exception:
                    pass
                try:
                    pg.reload(wait_until='domcontentloaded', timeout=20000)
                except Exception:
                    pass
                time.sleep(5)
            else:
                break
        # LEARNED (Bobur 2026-09-01): when a robot check appears after a redirect,
        # RELOAD the page — it clears the "I'm not a robot"/challenge state.
        for rl in range(3):
            if is_cloudflare(pg) or has_recaptcha(pg):
                print(f"  STEP{step}: robot/CAPTCHA after redirect — reloading ({rl+1}/3)")
                snap(pg, f"step{step}_robot_reload{rl}")
                try:
                    pg.reload(wait_until='domcontentloaded', timeout=20000)
                except Exception:
                    pass
                time.sleep(4)
            else:
                break
        if is_cloudflare(pg):
            print(f"  STEP{step}: Cloudflare still present — waiting 8s")
            time.sleep(8)

        p = pct(pg)
        print(f"  --- STEP {step} | pct={p} | url ...{pg.url.split('/')[-1][:24]}")
        print(f"      head={heading(pg)}")

        # SELF-HEAL: if we've learned this pct is a trouble spot, pre-apply the fix.
        _lessons = load_lessons()
        _lk = f"stuck@pct{p}"
        if _lessons.get(_lk, {}).get('fix') == 'extra_reload_and_wait':
            print(f"  🧠 applying learned fix at {p}: extra reload + settle")
            try:
                pg.reload(wait_until='domcontentloaded', timeout=20000)
            except Exception:
                pass
            time.sleep(random.uniform(4, 6))

        # human-like pause between steps
        time.sleep(random.uniform(0.8, 2.0))

        # scroll + full screenshots to see the WHOLE page
        scroll_and_snap(pg, f"step{step}")

        # confirmation already?
        conf = is_confirmation(pg)
        if conf:
            print(f"  🎉 CONFIRMATION reached: matched '{conf}'")
            snap(pg, f"CONFIRMED_step{step}")
            return 'submitted'

        # final submit page?
        if has_submit(pg):
            print(f"  >>> SUBMIT PAGE (pct={p}) — clicking Submit for REAL")
            snap(pg, f"before_submit_step{step}")
            # Try auto-solver / reload to clear any CAPTCHA. This MAY reload the page.
            wait_for_human_captcha(pg)
            # If a CAPTCHA is still present, re-loop (don't submit into a challenge).
            if has_recaptcha(pg):
                print("  ↻ CAPTCHA still present after solve attempt — re-looping")
                time.sleep(2)
                continue
            # The page may have reloaded during CAPTCHA clearing. Poll IN-PLACE for the
            # submit button to reappear (up to ~15s) instead of re-looping + re-solving.
            ready = has_submit(pg)
            for _w in range(8):
                if ready:
                    break
                time.sleep(2)
                ready = has_submit(pg)
            if not ready:
                print("  ↻ submit button still not ready — re-looping once")
                continue
            time.sleep(random.uniform(0.6, 1.4))  # human-like pause before clicking
            if click_submit(pg):
                print("  📨 clicked Submit — waiting for confirmation")
                try:
                    pg.wait_for_load_state('domcontentloaded', timeout=10000)
                except Exception:
                    pass
                time.sleep(5)
                scroll_and_snap(pg, f"after_submit_step{step}")
                conf = is_confirmation(pg)
                if conf:
                    print(f"  🎉 CONFIRMATION: matched '{conf}'")
                    snap(pg, "CONFIRMED_final")
                    try:
                        upsert_application(db, job_url=url, ats_type='indeed',
                                           status='submitted', match_score=70)
                        print("  💾 recorded to applications DB (won't retry next time)")
                    except Exception as _e:
                        print(f"  ⚠️ DB record failed: {str(_e)[:50]}")
                    # Also remember the TITLE so the same role under a new link is skipped.
                    try:
                        import json as _json
                        title = (job_title or '').strip()[:80]
                        # don't save nav chrome / empty
                        if title and 'skip to main content' not in title.lower():
                            f = 'data/applied_titles.json'
                            try:
                                s = set(_json.load(open(f)))
                            except Exception:
                                s = set()
                            s.add(title)
                            _json.dump(sorted(s), open(f, 'w'))
                            print(f"  💾 remembered title (won't reapply): {title[:45]}")
                    except Exception:
                        pass
                    return 'submitted'
                print("  ⚠️ Submit clicked but no confirmation text yet — saved screenshots to inspect")
                snap(pg, "after_submit_no_conf")
                return 'submitted_no_conf'
            print("  ⚠️ could not click Submit")
            record_lesson('submit_click_failed', step, p)
            return 'submit_click_failed'

        # questions page? FILL first (do NOT skip)
        if is_questions_page(pg):
            print(f"  📝 questions page at step {step} — filling")
            fill_questions_page(pg, db, profile, company='Employer')
            scroll_and_snap(pg, f"step{step}_after_fill")
            # LEARNED (Bobur): when the "I'm not a robot" checkbox appears here,
            # RELOAD the page and it goes away — then Continue works.
            # Reloading does NOT lose the filled answers (Indeed keeps them server-side),
            # but if it does, the loop will re-fill on the next pass.
            for rl in range(3):
                if has_recaptcha(pg):
                    print(f"  🔄 robot checkbox on questions page — reloading to clear ({rl+1}/3)")
                    snap(pg, f"step{step}_robot_before_reload{rl}")
                    try:
                        pg.reload(wait_until='domcontentloaded', timeout=20000)
                    except Exception:
                        pass
                    time.sleep(4)
                    # re-fill in case the reload cleared the answers
                    if is_questions_page(pg):
                        fill_questions_page(pg, db, profile, company='Employer')
                    snap(pg, f"step{step}_after_robot_reload{rl}")
                else:
                    break

        # advance with the VISIBLE Continue
        if click_continue(pg):
            print("      ➡️ clicked visible Continue")
            try:
                pg.wait_for_load_state('domcontentloaded', timeout=8000)
            except Exception:
                pass
            time.sleep(3)
        else:
            print(f"  ⚠️ no visible Continue and no Submit at step {step} — stuck")
            snap(pg, f"stuck_step{step}")
            # Diagnose EXACTLY what required field is still blocking.
            try:
                empties = pg.evaluate(r"""() => {
                    const out = [];
                    const names = new Set();
                    document.querySelectorAll('input[type=radio]').forEach(r => r.name && names.add(r.name));
                    names.forEach(n => {
                        const rs = [...document.querySelectorAll(`input[type=radio][name="${n}"]`)];
                        if (rs.length && !rs.some(r => r.checked) && rs[0].offsetParent)
                            out.push('radio-empty:' + n.slice(0,20));
                    });
                    document.querySelectorAll('[role=combobox]').forEach(c => {
                        if (c.offsetParent && /select an option/i.test(c.textContent))
                            out.push('dropdown-empty:' + (c.getAttribute('data-testid')||'').slice(0,30));
                    });
                    document.querySelectorAll('input[type=checkbox][required], input[type=checkbox][aria-required=true]').forEach(c => {
                        if (c.offsetParent && !c.checked) out.push('checkbox-required-empty');
                    });
                    document.querySelectorAll('textarea[required], input[required]').forEach(t => {
                        if (t.offsetParent && !(t.value||'').trim()) out.push('text-required-empty:' + (t.getAttribute('aria-label')||t.name||'').slice(0,25));
                    });
                    return out.slice(0, 15);
                }""")
                print(f"  🔎 remaining required-empty fields: {empties}")
            except Exception as _e:
                empties = ['?']
                print(f"  🔎 diagnose failed: {str(_e)[:50]}")
            # LAST RESORT: all fields filled but Continue not clicked → JS-click any
            # enabled 'Continue' button directly (handles sticky/footer buttons).
            if not empties:
                try:
                    did = pg.evaluate(r"""() => {
                        const b = [...document.querySelectorAll('button')].find(
                            x => !x.disabled && /^continue$/i.test(x.textContent.trim()));
                        if (b) { b.scrollIntoView({block:'center'}); b.click(); return true; }
                        return false;
                    }""")
                    if did:
                        print("  ➡️ JS-clicked Continue (last resort)")
                        try:
                            pg.wait_for_load_state('domcontentloaded', timeout=8000)
                        except Exception:
                            pass
                        time.sleep(3)
                        # if it advanced (pct changed or new page), continue the loop
                        if not is_questions_page(pg) or has_submit(pg):
                            continue
                        # re-check: still same page?
                        print("  🔎 after JS-click, still on questions page")
                except Exception as _e:
                    print(f"  JS-click failed: {str(_e)[:50]}")
            # ROOT CAUSE (Bobur screenshot): 'Something went wrong' server error freezes
            # the form. If present, OK + reload + re-fill and keep going (don't give up).
            if _has_indeed_error(pg):
                print("  🔁 'Something went wrong' — OK + reload + re-fill, then retry")
                try:
                    ok = pg.get_by_role("button", name="OK")
                    if ok.count() and ok.first.is_visible(timeout=1500):
                        ok.first.click(timeout=2500); time.sleep(1)
                except Exception:
                    pass
                try:
                    pg.reload(wait_until='domcontentloaded', timeout=20000)
                except Exception:
                    pass
                time.sleep(5)
                continue  # retry this step from the top (re-fill + advance)
            record_lesson('stuck', step, p, detail=str(empties)[:60])
            return 'stuck'

    print("  ⚠️ hit MAX_STEPS without reaching submit")
    return 'max_steps'


def main():
    from jobspy import scrape_jobs
    profile = json.load(open('config/profile.json'))
    db = sqlite3.connect('data/agent_memory.db')
    db.row_factory = sqlite3.Row
    init_db(db)

    print("Searching Indeed easy-apply jobs...")
    jobs = scrape_jobs(site_name=['indeed'],
                       search_term='Java Spring Boot developer contract remote',
                       location='USA', results_wanted=20, easy_apply=True)
    urls = [str(u) for u in jobs['job_url'].tolist() if str(u) != 'nan']
    print(f"Got {len(urls)} urls")
    cookies = load_cookies()

    with sync_playwright() as pw:
        # Headless by default (CI/CD has no display). Set HEADFUL=1 locally to watch
        # and to solve CAPTCHAs manually. Same code runs in CI and locally.
        _headful = os.environ.get('HEADFUL', '0') == '1'
        b = pw.chromium.launch(headless=not _headful,
                               args=['--disable-blink-features=AutomationControlled'])
        # Human-like context: rotating UA/viewport + Denver timezone (matches IP).
        try:
            from human_behavior import random_context_args
            ctx = b.new_context(**random_context_args())
            print("  🧑 human-like context (rotating UA/viewport/timezone)")
        except Exception:
            ctx = b.new_context(viewport={'width': 1000, 'height': 1300}, user_agent=(
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'))
        ctx.add_cookies(cookies)
        pg = ctx.new_page()

        target = int(os.environ.get('TARGET_SUBMITS', '2'))
        submitted_jobs = []

        import re
        JK_FILE = 'data/applied_jks.json'

        def _jk(u):
            m = re.search(r'jk=([0-9a-f]+)', u or '')
            return m.group(1) if m else ''

        def _load_jks():
            try:
                return set(json.load(open(JK_FILE)))
            except Exception:
                return set()

        def _save_jk(j):
            s = _load_jks()
            s.add(j)
            try:
                json.dump(sorted(s), open(JK_FILE, 'w'))
            except Exception:
                pass

        applied_jks = _load_jks()

        # Also pull jk ids from the applications DB (jobs applied in PRIOR sessions),
        # so we skip them WITHOUT opening the link (Bobur: don't waste time loading).
        try:
            for r in db.execute("SELECT job_url FROM applications "
                                "WHERE status IN ('applied','submitted','dry_run','applied_via_email')").fetchall():
                ju = r[0] if not hasattr(r, 'keys') else r['job_url']
                j = _jk(ju)
                if j:
                    applied_jks.add(j)
        except Exception:
            pass
        # Persist the enriched set so it's available immediately next run too.
        try:
            json.dump(sorted(applied_jks), open(JK_FILE, 'w'))
        except Exception:
            pass
        print(f"  🗂️  {len(applied_jks)} jobs pre-marked applied (skipped without opening)")

        # Failed/stalled jobs — skip them too so we don't waste time re-trying.
        FAILED_FILE = 'data/failed_jks.json'
        def _load_failed():
            try:
                return set(json.load(open(FAILED_FILE)))
            except Exception:
                return set()
        def _save_failed(j):
            s = _load_failed(); s.add(j)
            try:
                json.dump(sorted(s), open(FAILED_FILE, 'w'))
            except Exception:
                pass
        failed_jks = _load_failed()

        for url in urls:
            jk = _jk(url)
            if jk and jk in applied_jks:
                print(f"  ⏭️  already applied (jk={jk}) — skipping")
                continue
            if jk and jk in failed_jks:
                print(f"  ⏭️  previously failed (jk={jk}) — skipping to save time")
                continue
            try:
                result = submit_one(pg, url, db, profile)
            except Exception as e:
                print(f"  ERR {str(e)[:120]}")
                result = 'error'
            if result in ('submitted', 'submitted_no_conf') and jk:
                _save_jk(jk)
                applied_jks.add(jk)
            elif jk and result in ('stuck', 'cloudflare_stuck', 'no_apply_button',
                                   'submit_click_failed', 'error', 'max_steps'):
                _save_failed(jk)
                failed_jks.add(jk)
            if result in ('submitted', 'submitted_no_conf'):
                submitted_jobs.append(url)
                print(f"\n✅ SUBMITTED #{len(submitted_jobs)} — {url[-45:]}")
                if len(submitted_jobs) >= target:
                    break
            else:
                print(f"  -> {result}; trying next job")
                # FAILURE REPORT for debugging (per Bobur: screenshot + report so we fix).
                if result in ('stuck', 'submit_click_failed', 'max_steps', 'error'):
                    print(f"  ❌ FAILURE REPORT: job jk={jk} result={result}")
                    print(f"     latest screenshots: run `ls -t screenshots/submit_*stuck* | head`")

            # FOCUS_ONE: stop after the FIRST real attempt (skips don't count), so we
            # debug one application deeply before moving on.
            if os.environ.get('FOCUS_ONE') == '1' and result not in (
                    'email_confirmed_skip', 'no_apply_button', 'already_applied',
                    'cloudflare_stuck'):
                print(f"\n🎯 FOCUS_ONE: stopping after first real attempt (result={result})")
                break
        b.close()
    db.close()
    print(f"\n=== SUBMITTED {len(submitted_jobs)} APPLICATION(S) ===")
    for i, u in enumerate(submitted_jobs, 1):
        print(f"  {i}. {u}")
    print("Check screenshots/submit_*.png for every step, ending with each confirmation page.")


if __name__ == '__main__':
    main()
