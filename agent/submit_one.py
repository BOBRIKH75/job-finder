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

# ==========================================================================
# 🔒 LOCKED FLOW — DO NOT BREAK (approved + verified 2026-09-02)
# --------------------------------------------------------------------------
# This submit flow is PROVEN end-to-end: it submitted a REAL application
# (jk=34729111d7580f6e -> CONFIRMATION url:post-apply). It is APPROVED and FROZEN.
#
# RULES for any future change (me or a future session):
#   1. DO NOT modify the 4 LOCKED fixes below without Bobur's explicit approval.
#      They are marked in-code with:  #  >>> LOCKED FIX #n  ...  #  <<< LOCKED FIX #n
#        FIX #1  persistent real-Chrome launch (_launch)         — beats "Try again later"
#        FIX #2  Gemini model = gemini-flash-latest              — (src/gemini_captcha_solver.py)
#        FIX #3  single-option consent auto-click                — (src/questions_filler.py)
#        FIX #4  trust injected TOKEN, never reload-after-solve  — (x2 here)
#   2. To fix a DIFFERENT/NEW issue: add it as OPTIONAL/ADDITIVE, gated behind an
#      env flag (e.g. os.environ.get('EXPERIMENTAL_X') == '1'), default OFF.
#      Never change the locked path to fix an unrelated problem.
#   3. Only after the new fix is CONFIRMED working (real submit) may it be
#      promoted to default — and then update SESSION_MEMORY.md + this header.
#   4. Optimize ONLY after confirmation, and only in an optional path first.
# Full detail: SESSION_MEMORY.md "APPROVED + FROZEN" section + FLOW_LOCK.md.
# ==========================================================================

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
    """Screenshot the page. FAST mode (default) = one quick shot; FAST=0 = top/mid/bot."""
    if os.environ.get('FAST', '1') == '1':
        snap(page, tag)
        return
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
        # Submit is below a long resume preview — scroll to bottom so it's in the DOM/visible.
        try:
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
        return page.locator(
            '[data-testid="submit-application-button"], '
            'button:has-text("Submit your application"), '
            'button:has-text("Submit application")').count() > 0
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
                'button:has-text("Review details")',
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


def dismiss_distance_warning(page) -> bool:
    """DYNAMIC (additive): Indeed sometimes interrupts the flow with a 'this job looks
    like it might be a little far from you / About N miles away — make sure this job
    location still works for you' page. Bob is remote-preferred, so we always proceed.
    Detect the warning by TEXT (any distance), then click the proceed/continue button.
    Returns True if a warning was found and dismissed. No-op (False) otherwise."""
    try:
        body = (page.locator('body').inner_text(timeout=2000) or '').lower()
    except Exception:
        return False
    signals = ('far from you', 'miles away', 'still works for you',
               'this job location', 'a little far')
    if not any(s in body for s in signals):
        return False
    print("  📍 distance/location warning detected — proceeding (remote-preferred)")
    for sel in ['[data-testid="continue-button"]',
                'button:has-text("Continue")',
                'button:has-text("Apply anyway")',
                'button:has-text("Continue application")',
                'button:has-text("Yes")',
                'a:has-text("Continue")']:
        loc = page.locator(sel)
        for i in range(min(loc.count(), 6)):
            el = loc.nth(i)
            try:
                if el.is_visible(timeout=1000):
                    el.scroll_into_view_if_needed(timeout=1500)
                    try:
                        el.click(timeout=3000)
                    except Exception:
                        el.evaluate("(b) => b.click()")
                    time.sleep(2)
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


def click_not_a_robot(page) -> bool:
    """Directly click the reCAPTCHA v2 'I'm not a robot' anchor checkbox.

    This is the box in the Indeed review-module page (the user's ask: "click the
    I'm not a robot box"). The checkbox lives inside an anchor iframe
    (src contains 'recaptcha/.../anchor'). Clicking it with a high-trust
    Patchright/Camoufox fingerprint usually clears the challenge with NO image
    grid. Returns True if the checkbox became checked / the challenge cleared.
    """
    try:
        # The anchor checkbox is inside the recaptcha ANCHOR iframe.
        anchor = None
        for fr in page.frames:
            src = (fr.url or '')
            if 'recaptcha' in src and 'anchor' in src:
                anchor = fr
                break
        if anchor is None:
            # Fallback: any recaptcha frame.
            anchor = next((f for f in page.frames if 'recaptcha' in (f.url or '')), None)
        if anchor is None:
            return False
        box = anchor.locator('#recaptcha-anchor, .recaptcha-checkbox, div[role="checkbox"]')
        if box.count() == 0:
            return False
        # Already checked?
        try:
            if anchor.locator('.recaptcha-checkbox-checked').count() > 0:
                return True
        except Exception:
            pass
        try:
            box.first.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        # Human jitter before clicking (research 2026: fixed/instant clicks lower the
        # reCAPTCHA trust score; a short random pause + a settling wait raises it).
        try:
            import random as _rnd
            time.sleep(_rnd.uniform(0.8, 2.1))
            box.first.hover(timeout=2000)
            time.sleep(_rnd.uniform(0.3, 0.9))
        except Exception:
            pass
        box.first.click(timeout=4000)
        print("   ☑️  clicked 'I'm not a robot' checkbox")
        # Give it a moment to turn into the green check (or pop an image grid).
        for _ in range(6):
            time.sleep(1)
            try:
                if anchor.locator('.recaptcha-checkbox-checked').count() > 0:
                    print("   ✅ 'I'm not a robot' now checked (no image challenge)")
                    return True
            except Exception:
                pass
            if not has_recaptcha(page):
                return True
        return False
    except Exception as _e:
        print(f"   ⚠️ not-a-robot click n/a: {str(_e)[:60]}")
        return False


# reCAPTCHA tokens expire ~120s after issue. We stamp when a token was last seen
# and, right before Submit, re-solve if it is older than this budget. Dynamic +
# TTL-based (additive to the locked flow — does not alter the locked success path).
_RECAPTCHA_TTL_SECONDS = 110  # safety margin under Google's ~120s hard expiry
_last_token_at = {'ts': 0.0, 'val': ''}


def _current_recaptcha_token(page) -> str:
    """Return the current g-recaptcha-response token value (or '')."""
    try:
        return page.evaluate(
            """() => {
                const els = document.querySelectorAll(
                  '[name="g-recaptcha-response"], [name="recaptcha-token"], textarea[id*="recaptcha"]');
                for (const e of els) { if (e.value && e.value.length > 20) return e.value; }
                return '';
            }""") or ''
    except Exception:
        return ''


def _stamp_token_if_present(page):
    """If a fresh token is on the page, record it + the time it was seen."""
    tok = _current_recaptcha_token(page)
    if tok and tok != _last_token_at['val']:
        _last_token_at['val'] = tok
        _last_token_at['ts'] = time.time()
    return tok


def ensure_fresh_captcha_token(page) -> bool:
    """DYNAMIC TTL GUARD (call right before Submit). If the page has a reCAPTCHA and
    the last-seen token is stale (older than the TTL budget) OR missing, re-run the
    solver chain so the token Indeed receives is valid. Returns True if the page has
    a usable/fresh token (or no captcha at all)."""
    if not has_recaptcha(page):
        return True
    tok = _stamp_token_if_present(page)
    age = time.time() - _last_token_at['ts'] if _last_token_at['ts'] else 1e9
    if tok and age <= _RECAPTCHA_TTL_SECONDS:
        return True  # token still fresh — nothing to do
    if tok:
        print(f"  ⏳ reCAPTCHA token stale ({int(age)}s > {_RECAPTCHA_TTL_SECONDS}s) — re-solving before Submit")
    else:
        print("  🔄 no fresh reCAPTCHA token before Submit — solving now")
    wait_for_human_captcha(page)          # re-run the (locked) dynamic solver chain
    tok = _stamp_token_if_present(page)   # re-stamp with the new token
    return bool(tok) or not has_recaptcha(page)


def wait_for_human_captcha(page, max_wait=180):
    """Solve reCAPTCHA FULLY DYNAMICALLY — NO human handoff (Bobur's rule 2026-09-02).

    Order (all automatic):
      0. Click the 'I'm not a robot' checkbox FIRST (high-trust fingerprint often
         clears a v2 checkbox with no image grid on this single click).
      1. FREE ClickSolver (playwright-captcha) — clicks + solves using browser stealth.
      2. Existing dynamic solver chain (_try_auto_captcha_solve): NopeCHA -> audio
         (playwright-recaptcha) -> OhMyCaptcha/Gemini -> hCaptcha/enterprise token.
      3. Reload to clear (reloading often drops the checkbox).
    If it still isn't cleared, RETURN False (caller skips the job) — we never block
    on a human. `max_wait` is kept only for signature compatibility.
    """
    if not has_recaptcha(page):
        return True

    # 0) Click 'I'm not a robot' FIRST (both headful + headless).
    if click_not_a_robot(page) and not has_recaptcha(page):
        print("   ✅ reCAPTCHA cleared by direct checkbox click")
        snap(page, "CAPTCHA_checkbox_cleared")
        return True

    # 1) FREE ClickSolver (playwright-captcha) — best with Patchright/Camoufox. No key.
    try:
        from playwright_captcha import ClickSolver, CaptchaType, FrameworkType
        fw = FrameworkType.PATCHRIGHT if _STEALTH == 'patchright' else FrameworkType.PLAYWRIGHT
        with ClickSolver(framework=fw, page=page, max_attempts=3, attempt_delay=3) as _cs:
            for _ct in (CaptchaType.RECAPTCHA_V2, CaptchaType.RECAPTCHA_V3):
                try:
                    _cs.solve_captcha(captcha_container=page, captcha_type=_ct)
                except Exception:
                    continue
        if not has_recaptcha(page):
            print("   ✅ free ClickSolver cleared the reCAPTCHA")
            snap(page, "CAPTCHA_clicksolved")
            return True
    except Exception as _e:
        print(f"   ⚠️ ClickSolver n/a: {str(_e)[:50]}")

    # 2) Existing dynamic solver chain (NopeCHA/audio/Gemini/hCaptcha/enterprise token).
    # >>> LOCKED FIX #4a (do not change without approval) — trust token, no reload
    #    IMPORTANT: when a solver SUCCEEDS it injects a valid g-recaptcha-response
    #    token into the hidden field. The visible widget iframe often STAYS in the
    #    DOM after that — so `has_recaptcha()` still returns True even though the
    #    challenge is effectively solved. We must TRUST the solver's success and
    #    NOT reload (reloading throws the token away and bounces the flow back to
    #    step 0 → the old `submit_click_failed@pct38%` bug). Verify by token presence.
    if _try_auto_captcha_solve is not None:
        try:
            print("   🔓 trying dynamic auto-captcha solver chain...")
            if _try_auto_captcha_solve(page):
                # Confirm a real token landed in the response field (widget may linger).
                _has_token = False
                try:
                    _has_token = bool(page.evaluate(
                        """() => {
                            const els = document.querySelectorAll(
                              '[name="g-recaptcha-response"], [name="recaptcha-token"], textarea[id*="recaptcha"]');
                            for (const e of els) { if (e.value && e.value.length > 20) return true; }
                            return false;
                        }"""))
                except Exception:
                    _has_token = False
                if _has_token or not has_recaptcha(page):
                    print("   ✅ dynamic solver cleared the CAPTCHA (token injected)")
                    snap(page, "CAPTCHA_autosolved")
                    return True
        except Exception as _e:
            print(f"   ⚠️ auto-solver error: {str(_e)[:60]}")
    # <<< LOCKED FIX #4a

    # 3) Reload to clear (LEARNED: reloading often removes the checkbox), then
    #    re-click the box + retry the solver once.
    for rl in range(2):
        if not has_recaptcha(page):
            print("   ✅ CAPTCHA cleared after reload")
            return True
        print(f"   🔄 reloading to clear CAPTCHA ({rl + 1}/2)")
        try:
            page.reload(wait_until='domcontentloaded', timeout=20000)
        except Exception:
            pass
        time.sleep(4)
        if click_not_a_robot(page) and not has_recaptcha(page):
            print("   ✅ reCAPTCHA cleared by checkbox click after reload")
            return True

    if not has_recaptcha(page):
        return True

    # No human handoff. Report unsolved so the caller skips this job and moves on.
    print("   ⚠️ reCAPTCHA not cleared by dynamic solvers — skipping job (no human wait)")
    snap(page, "CAPTCHA_unsolved_skip")
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
                    # Record this jk so NEXT time it's skipped BEFORE opening the link.
                    try:
                        m = _re.search(r'jk=([0-9a-f]+)', url or '')
                        if m:
                            jkf = 'data/applied_jks.json'
                            try:
                                js = set(_json.load(open(jkf)))
                            except Exception:
                                js = set()
                            js.add(m.group(1))
                            _json.dump(sorted(js), open(jkf, 'w'))
                    except Exception:
                        pass
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

    # FIRST-PAGE FAST-SKIP (Bobur): if Apply-with-Indeed did NOT reach the SmartApply
    # flow (still on the job view, no apply form), skip fast — don't waste time.
    try:
        _u = (pg.url or '').lower()
        _reached = ('smartapply' in _u or 'indeedapply' in _u or 'resume-selection' in _u
                    or is_questions_page(pg) or has_submit(pg))
        if not _reached and not is_cloudflare(pg):
            print("  ⏭️  Apply did not open the SmartApply flow — skipping fast")
            snap(pg, "SKIP_apply_no_flow")
            return 'no_apply_button'
    except Exception:
        pass

    # STEP 5-10: loop each page
    _no_progress = 0
    _last_pct = None
    _force_tries = 0
    _submit_attempts = 0
    _reached_submit_once = False
    for step in range(MAX_STEPS):
        # DYNAMIC (additive): clear Indeed's 'job is far from you' location warning
        # if present, so the flow proceeds (Bob is remote-preferred). No-op otherwise.
        try:
            dismiss_distance_warning(pg)
        except Exception:
            pass
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

        # LOOP DETECTION (Bobur): if we already hit the submit page once and the flow
        # BOUNCED BACK to resume-selection/38% (submit didn't take), stop — don't re-do
        # the same job and burn time. Record jk so it's skipped pre-open next time.
        if _reached_submit_once and ('resume-selection' in pg.url.lower() or p == '38%'):
            print("  🛑 flow bounced back to start after submit — submit didn't take, skipping job")
            snap(pg, f"SUBMIT_BOUNCE_step{step}")
            try:
                import re as _re, json as _json
                m = _re.search(r'jk=([0-9a-f]+)', url or '')
                if m:
                    jkf = 'data/failed_jks.json'
                    try:
                        fs = set(_json.load(open(jkf)))
                    except Exception:
                        fs = set()
                    fs.add(m.group(1)); _json.dump(sorted(fs), open(jkf, 'w'))
            except Exception:
                pass
            record_lesson('submit_click_failed', step, p)
            return 'submit_click_failed'

        # human-like pause between steps (short — perf)
        time.sleep(random.uniform(0.4, 1.0))

        # scroll + full screenshots to see the WHOLE page
        scroll_and_snap(pg, f"step{step}")

        # confirmation already?
        conf = is_confirmation(pg)
        if conf:
            print(f"  🎉 CONFIRMATION reached: matched '{conf}'")
            snap(pg, f"CONFIRMED_step{step}")
            return 'submitted'

        # If at the FINAL review page (review-module) only — NOT structured-data-review.
        if p == '100%' or 'review-module' in pg.url.lower():
            snap(pg, f"review_page_step{step}")  # learn: capture the review page
            # 1) give the review page + its reCAPTCHA time to load
            time.sleep(2)
            try:
                pg.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            time.sleep(1.5)
            # 2) if no Submit yet, the reCAPTCHA likely hasn't validated — solve it first.
            if not has_submit(pg):
                print("  🔐 review page — solving reCAPTCHA first (Submit appears after it)")
                wait_for_human_captcha(pg)   # solver chain + reload-to-clear
                time.sleep(2)
                try:
                    pg.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                except Exception:
                    pass
                # poll for Submit to render after CAPTCHA cleared
                for _w in range(6):
                    if has_submit(pg):
                        break
                    time.sleep(2)
                if not has_submit(pg):
                    # last resort: reload the review page to force Submit to render
                    print("  ↻ still no Submit — reloading review page once")
                    try:
                        pg.reload(wait_until='domcontentloaded', timeout=20000)
                    except Exception:
                        pass
                    time.sleep(4)
                    wait_for_human_captcha(pg)
                    time.sleep(2)
                snap(pg, f"review_after_captcha_step{step}")

        # final submit page?
        if has_submit(pg):
            print(f"  >>> SUBMIT PAGE (pct={p}) — clicking Submit for REAL")
            snap(pg, f"before_submit_step{step}")
            _reached_submit_once = True
            _submit_attempts += 1
            if _submit_attempts > 3:
                print("  🛑 reached submit page 3x without confirming — skipping job (anti-loop)")
                snap(pg, f"SUBMIT_LOOP_step{step}")
                record_lesson('submit_click_failed', step, p)
                return 'submit_click_failed'
            # >>> LOCKED FIX #4b (do not change without approval) — trust token, no reload
            # Try auto-solver / reload to clear any CAPTCHA. This MAY reload the page.
            wait_for_human_captcha(pg)
            # If a CAPTCHA is still present AND no token was injected, re-loop (don't
            # submit into an unsolved challenge). But if a valid token IS present, the
            # widget just lingers in the DOM — proceed to Submit (don't reload/bounce).
            _tok = False
            try:
                _tok = bool(pg.evaluate(
                    """() => {
                        const els = document.querySelectorAll(
                          '[name="g-recaptcha-response"], [name="recaptcha-token"], textarea[id*="recaptcha"]');
                        for (const e of els) { if (e.value && e.value.length > 20) return true; }
                        return false;
                    }"""))
            except Exception:
                _tok = False
            if has_recaptcha(pg) and not _tok:
                print("  ↻ CAPTCHA still present after solve attempt — re-looping")
                time.sleep(2)
                continue
            # <<< LOCKED FIX #4b
            # CAPTCHA cleared — scroll to bottom (75s human solve may have moved view),
            # then poll for the Submit button to be present before clicking.
            try:
                pg.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            time.sleep(1.5)
            ready = has_submit(pg)
            for _w in range(10):
                if ready:
                    break
                time.sleep(1.5)
                try:
                    pg.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                except Exception:
                    pass
                ready = has_submit(pg)
            if not ready:
                print("  ↻ submit button still not ready — re-looping once")
                continue
            time.sleep(random.uniform(0.6, 1.4))  # human-like pause before clicking
            # DYNAMIC TTL GUARD: re-solve if the reCAPTCHA token went stale while we
            # were filling later steps (Google expires it ~120s after issue).
            ensure_fresh_captcha_token(pg)
            if click_submit(pg):
                print("  📨 clicked Submit — waiting for confirmation")
                try:
                    pg.wait_for_load_state('domcontentloaded', timeout=10000)
                except Exception:
                    pass
                # Wait longer + re-check twice (confirmation can lag after CAPTCHA/reload).
                conf = None
                for _c in range(3):
                    time.sleep(4)
                    conf = is_confirmation(pg)
                    if conf:
                        break
                scroll_and_snap(pg, f"after_submit_step{step}")
                if conf:
                    print(f"  🎉 CONFIRMATION: matched '{conf}'")
                    snap(pg, "CONFIRMED_final")
                    try:
                        _company = (locals().get('job_company') or locals().get('employer')
                                    or (job_title or '').strip() or 'Indeed Employer')
                        _title = (locals().get('job_title') or '').strip() or 'Indeed Job'
                        upsert_application(db, job_url=url, ats_type='indeed',
                                           status='submitted', match_score=70,
                                           company=_company, job_title=_title)
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
            _nfilled = fill_questions_page(pg, db, profile, company='Employer')
            scroll_and_snap(pg, f"step{step}_after_fill")
            _pnow = pct(pg)
            # On 0-fill, check if required fields are actually EMPTY. If none empty,
            # the page is READY — try hard to advance (Review/Continue) rather than
            # counting it as stuck (fixes false stall when everything is already filled).
            if (_nfilled or 0) == 0 and _pnow == _last_pct:
                _empty_now = 0
                try:
                    _empty_now = pg.evaluate(r"""() => {
                        let n=0; const names=new Set();
                        document.querySelectorAll('input[type=radio]').forEach(r=>r.name&&names.add(r.name));
                        names.forEach(nm=>{const rs=[...document.querySelectorAll(`input[type=radio][name="${nm}"]`)];
                          if(rs.length&&!rs.some(r=>r.checked)&&rs[0].offsetParent)n++;});
                        document.querySelectorAll('[role=combobox]').forEach(c=>{if(c.offsetParent&&/select an option/i.test(c.textContent))n++;});
                        document.querySelectorAll('textarea[required],input[required]').forEach(t=>{if(t.offsetParent&&!(t.value||'').trim())n++;});
                        return n;
                    }""")
                except Exception:
                    _empty_now = 1
                if _empty_now == 0:
                    # Everything my filler sees is filled. But a hidden required control
                    # (e.g. "Agree" privacy consent) may remain. Try consent + advance,
                    # cap at 3 tries, then screenshot + skip (NOT infinite loop).
                    _force_tries += 1
                    print(f"  ✅ all visible filled — force-advance try {_force_tries}/3")
                    try:
                        pg.evaluate(r"""() => {
                            // click any 'Agree'/single consent option first
                            [...document.querySelectorAll('label,button,[role=option],[role=radio],input')].forEach(e=>{
                                const t=(e.textContent||e.value||'').trim().toLowerCase();
                                if(t==='agree'||t==='i agree'){ e.click(); }
                            });
                            // open + pick the first non-placeholder option in any 'select an option' consent dropdown
                            const cb=[...document.querySelectorAll('[role=combobox]')].find(c=>c.offsetParent&&/select an option|agree/i.test(c.textContent));
                            if(cb){cb.click();}
                        }""")
                        time.sleep(1)
                        pg.evaluate(r"""() => {
                            const o=[...document.querySelectorAll('[role=option]')].find(e=>e.offsetParent&&/agree/i.test(e.textContent));
                            if(o)o.click();
                            const b=[...document.querySelectorAll('button')].find(x=>!x.disabled&&/review your application|^continue$/i.test(x.textContent.trim()));
                            if(b){b.scrollIntoView({block:'center'});b.click();}
                        }""")
                    except Exception:
                        pass
                    time.sleep(3)
                    if _force_tries >= 3 and pct(pg) == _pnow:
                        print(f"  🛑 3 force-advance tries failed at {_pnow} — screenshot + skip")
                        snap(pg, f"NOPROGRESS_step{step}")
                        record_lesson('stuck', step, _pnow)
                        return 'stuck'
                    _no_progress = 0
                    _last_pct = _pnow
                    continue
                _no_progress += 1
            else:
                _no_progress = 0
            _last_pct = _pnow
            if _no_progress >= 2:
                print(f"  🛑 no progress 2x at {_pnow} — screenshot + capture + skip (learn for next run)")
                snap(pg, f"NOPROGRESS_step{step}")
                try:
                    qtexts = pg.evaluate(r"""() => {
                        const out=[]; const names=new Set();
                        document.querySelectorAll('input[type=radio]').forEach(r=>r.name&&names.add(r.name));
                        names.forEach(n=>{const rs=[...document.querySelectorAll(`input[type=radio][name="${n}"]`)];
                          if(!rs.length||rs.some(r=>r.checked)||!rs[0].offsetParent)return;
                          let q='',d=rs[0].closest('div');
                          for(let k=0;k<6&&d;k++){for(const t of d.querySelectorAll('legend,h2,h3,h4,label,p,span')){const tx=(t.textContent||'').trim();if(tx.length>q.length&&tx.length>12&&tx.length<400&&!/^(yes|no)\b/i.test(tx)&&(tx.includes('?')||tx.includes('*')||tx.split(' ').length>4))q=tx;}if(q)break;d=d.parentElement;}
                          const opts=rs.map(r=>{let l='';if(r.id){const e=document.querySelector(`label[for="${r.id}"]`);if(e)l=e.textContent.trim();}return l;}).filter(Boolean);
                          if(q)out.push({q,opts,type:'radio'});});
                        return out.slice(0,20);
                    }""")
                    if qtexts:
                        nrf='data/needs_resolution.json'
                        try: existing=json.load(open(nrf))
                        except Exception: existing=[]
                        seen={e['q'] for e in existing}
                        for qt in qtexts:
                            if qt['q'] not in seen: existing.append(qt)
                        os.makedirs('data',exist_ok=True); json.dump(existing,open(nrf,'w'),indent=2)
                        print(f"  🧠 saved {len(qtexts)} unresolved → next run AI-resolves")
                except Exception:
                    pass
                record_lesson('stuck', step, _pnow)
                return 'stuck'
            # LEARNED (Bobur): when the "I'm not a robot" checkbox appears here,
            # RELOAD the page and it goes away — then Continue works.
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
            # DYNAMIC SELF-HEAL (Bobur's design): if fields remain empty, capture the
            # actual QUESTION TEXTS + options and save them so NEXT run pre-resolves
            # them via AI into memory → passes cleanly next time.
            if empties and empties != ['?']:
                try:
                    qtexts = pg.evaluate(r"""() => {
                        const out = [];
                        // radio groups not answered -> capture question text + options
                        const names = new Set();
                        document.querySelectorAll('input[type=radio]').forEach(r => r.name && names.add(r.name));
                        names.forEach(n => {
                            const rs = [...document.querySelectorAll(`input[type=radio][name="${n}"]`)];
                            if (!rs.length || rs.some(r => r.checked) || !rs[0].offsetParent) return;
                            let q = '', d = rs[0].closest('div');
                            for (let k=0; k<6 && d; k++) {
                                for (const t of d.querySelectorAll('legend,h2,h3,h4,label,p,span')) {
                                    const tx=(t.textContent||'').trim();
                                    if (tx.length>q.length && tx.length>12 && tx.length<400 &&
                                        !/^(yes|no)\b/i.test(tx) && (tx.includes('?')||tx.includes('*')||tx.split(' ').length>4)) q=tx;
                                }
                                if (q) break; d = d.parentElement;
                            }
                            const opts = rs.map(r => { let l=''; if(r.id){const e=document.querySelector(`label[for="${r.id}"]`); if(e)l=e.textContent.trim();} return l; }).filter(Boolean);
                            if (q) out.push({q, opts, type:'radio'});
                        });
                        return out.slice(0, 20);
                    }""")
                    if qtexts:
                        nrf = 'data/needs_resolution.json'
                        try:
                            existing = json.load(open(nrf))
                        except Exception:
                            existing = []
                        seen = {e['q'] for e in existing}
                        for qt in qtexts:
                            if qt['q'] not in seen:
                                existing.append(qt)
                        os.makedirs('data', exist_ok=True)
                        json.dump(existing, open(nrf, 'w'), indent=2)
                        print(f"  🧠 saved {len(qtexts)} unresolved question(s) → next run AI-resolves them")
                except Exception as _e:
                    print(f"  🧠 capture failed: {str(_e)[:50]}")
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

    # DYNAMIC SELF-HEAL: pre-resolve questions that stalled us before, via AI, into
    # memory — so this run answers them instantly (Bobur: next run comes with the fix).
    try:
        from question_answerer import answer_question as _aq
        nrf = 'data/needs_resolution.json'
        pending = json.load(open(nrf))
        if pending:
            resolved = 0
            for item in pending:
                a = _aq(db, item['q'], field_type=item.get('type', 'radio'),
                        options=item.get('opts'), profile=profile)
                if a:
                    resolved += 1
            print(f"  🧠 self-heal: pre-resolved {resolved}/{len(pending)} previously-stuck questions via AI")
            # clear the ones now in memory (keep file small)
            json.dump([], open(nrf, 'w'))
    except Exception:
        pass

    print("Searching Indeed easy-apply jobs...")

    def _extract_urls(df):
        """Safely pull job_url values from a jobspy DataFrame that may be empty
        or missing the column (Indeed rate-limits/blocks return an empty frame)."""
        try:
            if df is None or getattr(df, 'empty', True):
                return []
            if 'job_url' not in df.columns:
                return []
            return [str(u) for u in df['job_url'].tolist() if str(u) not in ('nan', '', 'None')]
        except Exception:
            return []

    # Allow forcing ONE specific job by URL (test loop: prove a real submit).
    forced = os.environ.get('TARGET_URL', '').strip()
    if forced:
        urls = [forced]
        print(f"  🎯 TARGET_URL set — testing exactly one job: {forced[:60]}")
    else:
        # Try the requested term, then fall back through a few terms if Indeed
        # returns nothing (rate-limit / block) so the run never crashes on an
        # empty result set. VERIFIED BUG 2026-09-02: an empty frame raised
        # KeyError: 'job_url' and killed the whole run.
        _terms = [os.environ.get('SEARCH_TERM', 'Java Spring Boot developer contract remote')]
        _terms += [
            'Java developer remote contract',
            'Senior Java backend developer remote',
            'Spring Boot developer remote',
        ]
        _loc = os.environ.get('SEARCH_LOCATION', 'USA')
        _rw = int(os.environ.get('RESULTS_WANTED', '20'))
        urls = []
        for _t in _terms:
            try:
                jobs = scrape_jobs(site_name=['indeed'], search_term=_t,
                                   location=_loc, results_wanted=_rw, easy_apply=True)
            except Exception as _e:
                print(f"  ⚠️ search '{_t[:40]}' errored: {str(_e)[:60]}")
                continue
            urls = _extract_urls(jobs)
            print(f"  🔍 '{_t[:45]}' → {len(urls)} urls")
            if urls:
                break
            time.sleep(2)  # brief backoff before the next term

    if not urls:
        print("❌ No jobs found (Indeed likely rate-limited/blocked the search). "
              "Try again shortly, use TARGET_URL=<job link>, or run from a residential IP.")
        return
    print(f"Got {len(urls)} urls")
    cookies = load_cookies()

    with sync_playwright() as pw:
        # Headless by default (CI/CD has no display). Set HEADFUL=1 locally to watch.
        # reCAPTCHA is solved DYNAMICALLY (no human) — same code runs in CI + locally.
        _headful = os.environ.get('HEADFUL', '0') == '1'

        def _launch():
            """Launch browser + a fresh human-like context with cookies. Returns
            (browser, context, page). Used at start AND to RELAUNCH after the
            browser/context dies (fix-list #2: the time=0s cascade — one crash
            used to kill every subsequent job)."""
            # >>> LOCKED FIX #1 (do not change without approval) — persistent real Chrome
            # PATCHRIGHT BEST PRACTICE (official README "use Chrome without
            # Fingerprint Injection"): a PERSISTENT context on REAL Chrome, with
            # NO custom args and NO custom user_agent. This is what stops Google's
            # "Try again later / automated queries" block — a fresh chromium.launch()
            # with a fake UA + manual --disable-blink-features (which patchright
            # already adds itself) gives a near-zero trust score. A persistent
            # profile keeps cookies/history across runs so Google trusts the session.
            _prof_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.chrome-profile')
            os.makedirs(_prof_dir, exist_ok=True)
            _launch_kw = dict(
                user_data_dir=_prof_dir,
                headless=not _headful,
                no_viewport=True,
            )
            if _STEALTH == 'patchright':
                # Real Google Chrome (channel="chrome") is required for full stealth.
                _launch_kw['channel'] = 'chrome'
            try:
                _ctx = pw.chromium.launch_persistent_context(**_launch_kw)
            except Exception:
                # Fallback: some machines lack channel="chrome" — retry on bundled Chromium.
                _launch_kw.pop('channel', None)
                _ctx = pw.chromium.launch_persistent_context(**_launch_kw)
            try:
                _ctx.add_cookies(cookies)
            except Exception:
                pass
            # launch_persistent_context returns the context (its own browser); reuse
            # an existing page if Chrome opened one, else create a fresh page.
            _pg = _ctx.pages[0] if _ctx.pages else _ctx.new_page()
            return _ctx, _ctx, _pg
            # <<< LOCKED FIX #1

        b, ctx, pg = _launch()
        print("  🧑 human-like context (rotating UA/viewport/timezone)")

        def _page_alive(_pg):
            """True if the page/context/browser is still usable."""
            try:
                return _pg is not None and not _pg.is_closed()
            except Exception:
                return False

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
        # TEST/RETRY mode: when RETRY_FAILED=1, do NOT skip previously-failed jobs.
        # After a filler/answer bug fix we WANT to re-attempt the jobs that stalled
        # before, so the fix is proven on a real submit (Bobur: loop until confirmed).
        if os.environ.get('RETRY_FAILED', '0') == '1':
            print(f"  ♻️  RETRY_FAILED=1 — will re-attempt {len(failed_jks)} previously-failed job(s)")
            failed_jks = set()

        for url in urls:
            jk = _jk(url)
            if jk and jk in applied_jks:
                print(f"  ⏭️  already applied (jk={jk}) — skipping")
                continue
            if jk and jk in failed_jks:
                print(f"  ⏭️  previously failed (jk={jk}) — skipping to save time")
                continue
            # RELAUNCH GUARD (fix-list #2): if the browser/context died on a prior
            # job, revive it BEFORE the next goto so we don't cascade time=0s errors.
            if not _page_alive(pg):
                print("  ♻️  browser/context was dead — relaunching before next job")
                try:
                    b.close()
                except Exception:
                    pass
                try:
                    b, ctx, pg = _launch()
                except Exception as _re:
                    print(f"  ❌ relaunch failed: {str(_re)[:80]} — stopping run")
                    break
            try:
                _job_start = time.time()
                result = submit_one(pg, url, db, profile)
                _job_elapsed = time.time() - _job_start
            except Exception as e:
                _emsg = str(e)
                print(f"  ERR {_emsg[:120]}")
                result = 'error'
                _job_elapsed = time.time() - _job_start if '_job_start' in dir() else 0
                # Dead browser/context/page -> relaunch immediately so the NEXT
                # job runs on a live browser (prevents the whole-run cascade).
                if ('has been closed' in _emsg or 'Target page' in _emsg
                        or 'crash' in _emsg.lower() or not _page_alive(pg)):
                    print("  ♻️  detected dead browser — relaunching for next job")
                    try:
                        b.close()
                    except Exception:
                        pass
                    try:
                        b, ctx, pg = _launch()
                    except Exception as _re:
                        print(f"  ❌ relaunch failed: {str(_re)[:80]} — stopping run")
                        break
            if result in ('submitted', 'submitted_no_conf') and jk:
                _save_jk(jk)
                applied_jks.add(jk)
            elif jk and result in ('stuck', 'cloudflare_stuck', 'no_apply_button',
                                   'submit_click_failed', 'error', 'max_steps'):
                _save_failed(jk)
                failed_jks.add(jk)
            if result in ('submitted', 'submitted_no_conf'):
                submitted_jobs.append(url)
                print(f"\n✅ SUBMITTED #{len(submitted_jobs)} — {url[-45:]} (took {_job_elapsed:.0f}s)")
                if len(submitted_jobs) >= target:
                    break
            else:
                print(f"  -> {result}; trying next job")
                # FAILURE REPORT for debugging (per Bobur: screenshot + report + TIME).
                if result in ('stuck', 'submit_click_failed', 'max_steps', 'error'):
                    print(f"  ❌ FAILURE REPORT: job jk={jk} result={result} time={_job_elapsed:.0f}s")
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
