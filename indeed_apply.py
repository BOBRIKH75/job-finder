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
import sys
import time

sys.path.insert(0, 'agent')

from src.memory import get_db, init_db, application_exists, upsert_application
from src.form_filler import load_profile


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
        
        # Pick 3 queries per run (rotate daily)
        day_offset = datetime.now().timetuple().tm_yday % max(len(SEARCHES), 1)
        queries = SEARCHES[day_offset:day_offset+3] if day_offset+3 <= len(SEARCHES) else SEARCHES[day_offset:] + SEARCHES[:3-(len(SEARCHES)-day_offset)]
        
        all_jobs = []
        for q in queries:
            try:
                batch = scrape_jobs(
                    site_name=['indeed'],
                    search_term=q,
                    location='USA',
                    results_wanted=20,
                    hours_old=48,
                    job_type='contract',
                    is_remote=True,
                )
                all_jobs.append(batch)
                print(f"  🔍 '{q}' → {len(batch)} jobs")
            except Exception as e:
                print(f"  ⚠️ '{q}' failed: {str(e)[:40]}")
        
        jobs = pd.concat(all_jobs, ignore_index=True).drop_duplicates(subset=['job_url']) if all_jobs else pd.DataFrame()
        print(f"🔍 Found {len(jobs)} Indeed contract jobs (from {len(queries)} searches)")
        # Filter to Easy Apply only (if jobspy provides the field)
        if 'is_remote' in jobs.columns:
            pass  # jobspy doesn't reliably filter easy apply
        # We'll detect Easy Apply at runtime — if no Apply button found, save for manual
        # Separate Easy Apply vs External Apply
        if 'is_remote' in jobs.columns:
            pass  # just for structure
    except Exception as e:
        print(f"⚠️ JobSpy search failed: {e}")
        return

    applied = 0
    failed = []
    skipped = 0
    MAX_APPS = 20

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ Playwright not installed — run: pip install playwright && playwright install chromium")
        return

    state_file = 'agent/data/indeed_state.json'
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
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

        # Quick cookie validity check
        try:
            page.goto('https://www.indeed.com/account/view', wait_until='domcontentloaded', timeout=10000)
            time.sleep(2)
            page_text = page.locator('body').inner_text(timeout=3000).lower()
            if 'sign in' in page_text or 'log in' in page_text:
                print("❌ Indeed cookies expired — skipping. Run refresh-cookies workflow.")
                browser.close()
                return
            print("✅ Indeed cookies valid")
        except Exception:
            print("⚠️ Cookie check inconclusive — proceeding anyway")

        for _, row in jobs.iterrows():
            if applied >= MAX_APPS:
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

                # Look for Indeed Easy Apply button
                apply_btn = page.locator(
                    'button:has-text("Apply now"), '
                    'button:has-text("Easy Apply"), '
                    '#indeedApplyButton'
                )
                if apply_btn.count() > 0 and apply_btn.first.is_visible(timeout=3000):
                    apply_btn.first.click()
                    time.sleep(random.uniform(2, 4))

                    # Look for Continue/Submit in the apply modal
                    submitted = False
                    for btn_text in ['Continue', 'Submit your application', 'Apply', 'Submit']:
                        btn = page.locator(f'button:has-text("{btn_text}")')
                        if btn.count() > 0 and btn.first.is_visible(timeout=2000):
                            btn.first.click()
                            time.sleep(2)
                            submitted = True

                    # Check success
                    page_text = page.locator('body').inner_text(timeout=3000).lower()
                    if any(s in page_text for s in ['application submitted', 'applied', 'thank you']):
                        applied += 1
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
                        failed.append({
                            'url': url,
                            'title': title,
                            'company': company,
                            'reason': 'No success signal after submit',
                            'platform': 'indeed',
                            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                        })
                else:
                    failed.append({
                        'url': url,
                        'title': title,
                        'company': company,
                        'reason': 'No Easy Apply button found',
                        'platform': 'indeed',
                        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    })

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
