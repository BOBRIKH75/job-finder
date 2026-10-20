#!/usr/bin/env python3
"""Test the questions filler live: walk to the 50% questions page, FILL it,
click Continue, and verify the page advances (pct goes past 50 / reaches submit).
Screenshots before + after fill. Does NOT submit.
"""
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, '.')
sys.path.insert(0, 'src')
os.environ['ANSWERER_NO_ASK'] = '1'  # profile-only for this automated test

from playwright.sync_api import sync_playwright
from memory import init_db
from questions_filler import is_questions_page, fill_questions_page


def load_cookies():
    c = json.load(open('data/indeed_cookies.json'))
    for x in c:
        x['secure'] = bool(x.get('secure', False))
        if x.get('sameSite') not in ('Strict', 'Lax', 'None'):
            x['sameSite'] = 'Lax'
    return c


def is_cf(page):
    try:
        if '__cf_chl' in (page.url or ''):
            return True
        b = page.locator('body').inner_text(timeout=2000).lower()
        return 'verify you are human' in b or 'additional verification' in b
    except Exception:
        return False


def pct(page):
    try:
        lines = [l.strip() for l in page.locator('body').inner_text(timeout=3000).split('\n')]
        return next((l for l in lines if l.endswith('%') and l[:-1].isdigit()), '?')
    except Exception:
        return '?'


def click_continue(page):
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


def has_submit(page):
    return page.locator('[data-testid="submit-application-button"], '
                        'button:has-text("Submit your application")').count() > 0


def snap(page, tag):
    os.makedirs('screenshots', exist_ok=True)
    p = f"screenshots/qtest_{tag}.png"
    try:
        page.screenshot(path=p, full_page=False)
        print(f"    📸 {p}")
    except Exception:
        pass


def main():
    from jobspy import scrape_jobs
    profile = json.load(open('config/profile.json'))
    db = sqlite3.connect('data/agent_memory.db')
    db.row_factory = sqlite3.Row
    init_db(db)

    jobs = scrape_jobs(site_name=['indeed'],
                       search_term='Java Spring Boot developer contract remote',
                       location='USA', results_wanted=15, easy_apply=True)
    urls = [str(u) for u in jobs['job_url'].tolist() if str(u) != 'nan']
    ck = load_cookies()

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=False,
                               args=['--disable-blink-features=AutomationControlled'])
        ctx = b.new_context(viewport={'width': 1000, 'height': 1300}, user_agent=(
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'))
        ctx.add_cookies(ck)
        pg = ctx.new_page()
        tested = 0
        attempts = 0
        for url in urls:
            if tested >= 1 or attempts >= 6:
                break
            attempts += 1
            try:
                pg.goto(url, wait_until='domcontentloaded', timeout=20000)
                time.sleep(3)
                for _ in range(3):
                    if not is_cf(pg):
                        break
                    pg.reload(wait_until='domcontentloaded', timeout=20000)
                    time.sleep(3)
                if is_cf(pg):
                    continue
                ab = pg.locator('button:has-text("Apply with Indeed"), span:has-text("Apply with Indeed")')
                if ab.count() == 0:
                    continue
                ab.first.click()
                time.sleep(5)
                reached_q = False
                stall = 0
                for step in range(16):
                    if has_submit(pg):
                        print(f"  step{step}: SUBMIT page (pct={pct(pg)}) reached_q={reached_q}")
                        snap(pg, 'reached_submit')
                        if reached_q:
                            tested += 1
                        break
                    if is_questions_page(pg):
                        reached_q = True
                        before = pct(pg)
                        print(f"  QUESTIONS PAGE step{step} (pct={before})")
                        n = fill_questions_page(pg, db, profile, company='Employer')
                        snap(pg, f'q_step{step}')
                        click_continue(pg)
                        try:
                            pg.wait_for_load_state('domcontentloaded', timeout=8000)
                        except Exception:
                            pass
                        time.sleep(3)
                        after = pct(pg)
                        print(f"    filled={n} pct {before} -> {after}")
                        if after == before:
                            stall += 1
                        else:
                            stall = 0
                        if stall >= 2:
                            print("  ❌ stalled on questions page 2x — dumping empties")
                            empties = pg.evaluate(
                                """() => {
                                    const out=[];
                                    document.querySelectorAll('textarea,input').forEach(t=>{if(t.offsetParent&&!(t.value||'').trim()&&t.type!=='hidden')out.push(t.tagName+':'+t.type+':'+(t.getAttribute('aria-label')||t.placeholder||'').slice(0,40))});
                                    document.querySelectorAll('[role=combobox]').forEach(c=>{if(c.offsetParent&&/select an option/i.test(c.textContent))out.push('dropdown-empty')});
                                    return out.slice(0,15);
                                }"""
                            )
                            print("  remaining empties:", empties)
                            snap(pg, f'stalled_step{step}')
                            break
                        continue
                    if not click_continue(pg):
                        print(f"  no continue at step{step} (pct={pct(pg)})")
                        break
                    try:
                        pg.wait_for_load_state('domcontentloaded', timeout=8000)
                    except Exception:
                        pass
                    time.sleep(3)
            except Exception as e:
                print(f"  ERR {str(e)[:100]}")
        b.close()
    db.close()


if __name__ == '__main__':
    main()
