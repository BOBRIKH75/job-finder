#!/usr/bin/env python3
"""SELF-TEACHING step-by-step walker for the Indeed SmartApply flow.

Loop taught by Bobur (2026-09-01):
  1. open job page
  2. reload up to 3 times, screenshot each reload (confirm it loaded)
  3. click "Apply with Indeed"
  4. on redirect -> screenshot
  5. BEFORE finding Continue: scroll top/middle/bottom, screenshot each (see WHOLE page)
  6. find visible Continue -> click
  7. wait -> screenshot -> record page type
  8. loop step 5-7 until the Submit page (do NOT submit)

All screenshots go to screenshots/, 900px wide (readable). Headed. Never submits.
Writes a JSON transcript of what each step looked like to data/flow_transcript.json.
"""
import json
import os
import sys
import time

sys.path.insert(0, '.')
from playwright.sync_api import sync_playwright

SHOT_DIR = 'screenshots'
TRANSCRIPT = 'data/flow_transcript.json'


def load_cookies():
    cookies = json.load(open('data/indeed_cookies.json'))
    for c in cookies:
        c['secure'] = bool(c.get('secure', False))
        if c.get('sameSite') not in ('Strict', 'Lax', 'None'):
            c['sameSite'] = 'Lax'
    return cookies


def snap(page, tag):
    """Screenshot current viewport at 900px wide."""
    os.makedirs(SHOT_DIR, exist_ok=True)
    path = f"{SHOT_DIR}/walk_{tag}.png"
    try:
        page.screenshot(path=path, full_page=False)
        print(f"    📸 {path}")
    except Exception as e:
        print(f"    shot fail {tag}: {str(e)[:50]}")
    return path


def scroll_and_snap(page, step):
    """Scroll top -> middle -> bottom, screenshot each so we see the whole page."""
    shots = []
    positions = [('top', 0.0), ('mid', 0.5), ('bot', 1.0)]
    for name, frac in positions:
        try:
            page.evaluate(f"() => window.scrollTo(0, document.body.scrollHeight * {frac})")
        except Exception:
            pass
        time.sleep(1.2)
        shots.append(snap(page, f"s{step}_{name}"))
    # back to top for clicking
    try:
        page.evaluate("() => window.scrollTo(0, 0)")
    except Exception:
        pass
    time.sleep(0.6)
    return shots


def is_cloudflare(page):
    try:
        if '__cf_chl' in (page.url or ''):
            return True
        body = page.locator('body').inner_text(timeout=2000).lower()
        return ('verify you are human' in body or 'additional verification' in body
                or 'checking your browser' in body)
    except Exception:
        return False


def page_info(page):
    try:
        body = page.locator('body').inner_text(timeout=3000)
        lines = [l.strip() for l in body.split('\n') if l.strip()]
        head = lines[:5]
        pct = next((l for l in lines if l.endswith('%') and l[:-1].isdigit()), '')
    except Exception:
        head, pct = [], ''
    try:
        btns = page.evaluate(
            """() => [...document.querySelectorAll('button:not([disabled]), [role="button"]')]
                .filter(b => b.offsetParent)
                .map(b => ({t:(b.textContent||'').trim().slice(0,30),
                            tid:b.getAttribute('data-testid')||''}))"""
        )
    except Exception:
        btns = []
    return head, pct, btns


def has_submit(page):
    try:
        return page.locator(
            '[data-testid="submit-application-button"], '
            'button:has-text("Submit your application")').count() > 0
    except Exception:
        return False


def click_visible_continue(page):
    for sel in ['[data-testid="continue-button"]', 'button:has-text("Continue")']:
        loc = page.locator(sel)
        for i in range(min(loc.count(), 8)):
            el = loc.nth(i)
            try:
                if el.is_visible(timeout=1200):
                    el.scroll_into_view_if_needed(timeout=2000)
                    el.click(timeout=4000)
                    return True
            except Exception:
                continue
    return False


def walk_one(pg, url, job_idx, transcript):
    print(f"\n===== JOB {job_idx}: {url[-30:]}")
    # 1-3. open + reload up to 3 times, screenshot each
    pg.goto(url, wait_until='domcontentloaded', timeout=20000)
    time.sleep(3)
    for r in range(3):
        snap(pg, f"job{job_idx}_open_reload{r}")
        if is_cloudflare(pg):
            print(f"  reload {r}: still Cloudflare, reloading again")
        else:
            print(f"  reload {r}: page loaded (url={pg.url[-30:]})")
        if r < 2:
            try:
                pg.reload(wait_until='domcontentloaded', timeout=20000)
            except Exception:
                pass
            time.sleep(3)
    if is_cloudflare(pg):
        print("  STILL Cloudflare after 3 reloads -> record + skip this job")
        transcript.append({'job': job_idx, 'url': url, 'result': 'cloudflare_stuck'})
        return
    # 4. click Apply with Indeed
    ab = pg.locator('button:has-text("Apply with Indeed"), span:has-text("Apply with Indeed")')
    if ab.count() == 0:
        print("  no 'Apply with Indeed' button -> record + skip")
        transcript.append({'job': job_idx, 'url': url, 'result': 'no_apply_button'})
        return
    print("  clicking 'Apply with Indeed'...")
    ab.first.click()
    time.sleep(5)

    # 5-8. loop each wizard step
    for step in range(14):
        if is_cloudflare(pg):
            print(f"  STEP{step}: Cloudflare on apply page — wait 8s")
            time.sleep(8)
        head, pct, btns = page_info(pg)
        print(f"  --- STEP {step} | pct={pct} | url={pg.url.split('/')[-1][:22]}")
        print(f"      head={head}")
        print(f"      buttons={[(x['t'], x['tid']) for x in btns]}")
        # scroll + full screenshots
        scroll_and_snap(pg, f"job{job_idx}_step{step}")
        transcript.append({
            'job': job_idx, 'step': step, 'pct': pct, 'url_slug': pg.url.split('/')[-1][:30],
            'head': head, 'buttons': [(x['t'], x['tid']) for x in btns],
            'has_submit': has_submit(pg),
        })
        if has_submit(pg):
            print(f"  >>> SUBMIT PAGE reached at step {step} (NOT clicking). Flow learned.")
            return
        if click_visible_continue(pg):
            print("      ➡️ clicked visible Continue")
            try:
                pg.wait_for_load_state('domcontentloaded', timeout=8000)
            except Exception:
                pass
            time.sleep(3)
        else:
            print("      ⚠️ no visible Continue and no Submit — STUCK. Recording page state.")
            transcript.append({'job': job_idx, 'step': step, 'result': 'stuck_no_continue'})
            return


def main():
    from jobspy import scrape_jobs
    print("Searching Indeed easy-apply jobs...")
    jobs = scrape_jobs(site_name=['indeed'],
                       search_term='Java Spring Boot developer contract remote',
                       location='USA', results_wanted=15, easy_apply=True)
    urls = [str(u) for u in jobs['job_url'].tolist() if str(u) != 'nan']
    print(f"Got {len(urls)} urls")
    cookies = load_cookies()
    transcript = []

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=False,
                               args=['--disable-blink-features=AutomationControlled'])
        ctx = b.new_context(viewport={'width': 900, 'height': 1200}, user_agent=(
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'))
        ctx.add_cookies(cookies)
        pg = ctx.new_page()
        walked = 0
        for url in urls:
            if walked >= 1:  # learn ONE full job this pass
                break
            try:
                walk_one(pg, url, walked, transcript)
                walked += 1
            except Exception as e:
                print(f"  ERR {str(e)[:100]}")
                walked += 1
        b.close()

    os.makedirs('data', exist_ok=True)
    json.dump(transcript, open(TRANSCRIPT, 'w'), indent=2)
    print(f"\nTranscript saved -> {TRANSCRIPT} ({len(transcript)} entries)")


if __name__ == '__main__':
    main()
