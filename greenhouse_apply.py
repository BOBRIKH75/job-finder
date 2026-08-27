#!/usr/bin/env python3
"""Dedicated Greenhouse applicator — handles email verification + reCAPTCHA.

Strategy per job:
1. Try direct API POST first (greenhouse_api.py) — fastest, no browser
2. If API fails → classify error via self_heal.py:
   - "already_applied" / "not_found" → skip (genuine dedup / job gone)
   - "otp_timeout" / "captcha" / "network" → retry submit_greenhouse_api with delay
   - "api_400" / "remix_context" / "form_field" → queue for Playwright browser batch
3. Browser batch: run_applications once for all queued jobs
4. Anything still failing → save to data/failed_jobs.json for next run
"""
import json
import os
import sys
import time
import random

os.environ['PYTHONUNBUFFERED'] = '1'
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

sys.path.insert(0, 'agent')

from src.portal_scanner import scan_greenhouse, load_companies
from src.greenhouse_api import submit_greenhouse_api
from src.form_filler import load_profile
from src.self_heal import classify_error, get_retry_config, STRATEGY
from src.memory import get_db, init_db, application_exists, upsert_application


def load_failed_jobs(failed_file: str) -> list:
    if os.path.exists(failed_file):
        try:
            return json.loads(open(failed_file).read()).get('jobs', [])
        except (json.JSONDecodeError, KeyError):
            return []
    return []


def save_failed_jobs(failed_file: str, jobs: list) -> None:
    jobs = jobs[-200:]
    os.makedirs(os.path.dirname(failed_file), exist_ok=True)
    with open(failed_file, 'w') as f:
        json.dump({'jobs': jobs, 'count': len(jobs)}, f, indent=2)


def _record_applied(db, company, title, url):
    upsert_application(db, company=company, job_title=title, job_url=url,
                       ats_type='greenhouse', match_score=80, status='applied')


def main():
    db = get_db()
    init_db(db)
    profile = load_profile()
    companies = load_companies()

    greenhouse_companies = companies.get('greenhouse', [])
    random.shuffle(greenhouse_companies)
    greenhouse_companies = greenhouse_companies[:15]
    print(f"🔍 Scanning {len(greenhouse_companies)} Greenhouse companies...")

    all_jobs = []
    for company in greenhouse_companies:
        try:
            all_jobs.extend(scan_greenhouse(company))
        except Exception as e:
            print(f"  ⚠️ {company}: {str(e)[:60]}")
        time.sleep(0.3)

    print(f"Found {len(all_jobs)} Greenhouse jobs matching skills")
    random.shuffle(all_jobs)

    applied = 0
    failed = []
    skipped = 0
    MAX_APPS = 30
    company_failures: dict = {}
    browser_queue: list = []

    # Resolve resume path once
    script_dir = os.path.dirname(os.path.abspath(__file__))
    resume_candidates = [
        os.path.join(script_dir, 'agent', 'resume.pdf'),
        os.path.join(script_dir, '..', 'agent', 'resume.pdf'),
        'agent/resume.pdf',
        'resume.pdf',
        os.path.expanduser('~/Downloads/CV/Bob_Rikh_Java_Backend_Developer_C2C.pdf'),
        os.path.expanduser('~/Downloads/CV/job-finder/agent/resume.pdf'),
    ]
    resume = profile.get('resume_path', '')
    if not resume or not os.path.exists(resume):
        resume = next((r for r in resume_candidates if os.path.exists(r)), 'agent/resume.pdf')
    print(f"  📁 Resume: {resume} (exists: {os.path.exists(resume)})")
    print(f"  📁 CWD: {os.getcwd()}")

    for job in all_jobs:
        if applied >= MAX_APPS:
            break

        url = job.get('url', '')
        if not url:
            continue
        if application_exists(db, url):
            skipped += 1
            continue

        title = job.get('title', '')
        company_name = job.get('company', '')

        if company_failures.get(company_name, 0) >= 3:
            continue

        # ── Strategy 1: Direct API POST ──────────────────────────────────────
        result = submit_greenhouse_api(url, profile, resume)

        if result.get('submitted'):
            applied += 1
            _record_applied(db, company_name, title, url)
            print(f"  ✅ {title} @ {company_name} (API)")
            time.sleep(1)
            continue

        # ── Self-heal: classify the error and decide what to do ──────────────
        error = result.get('error', 'unknown')
        error_type = classify_error(error)
        cfg = get_retry_config(error_type)

        job_entry = {
            'url': url, 'title': title, 'company': company_name,
            'reason': error, 'error_type': error_type,
            'platform': 'greenhouse', 'strategy_tried': 'api_only',
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
        }

        # Case 1: Not fixable — skip immediately
        if cfg["strategy"] == STRATEGY.SKIP:
            skipped += 1
            print(f"  ⏭️ {title}: {error_type} — skip")
            continue

        # Case 2: Queue for Playwright browser (form/API parse issues)
        if cfg["strategy"] == STRATEGY.USE_BROWSER:
            browser_queue.append(job_entry)
            print(f"  🌐 {title} @ {company_name}: {error_type} → browser queue")
            time.sleep(0.5)
            continue

        # Case 3: Retry submit_greenhouse_api (transient: network, captcha, otp_timeout)
        retry_success = False
        for attempt in range(1, cfg["max_retries"] + 1):
            print(f"  🔄 Retry {attempt}/{cfg['max_retries']} — {title} ({error_type}, wait {cfg['delay_s']}s)")
            time.sleep(cfg["delay_s"])

            result2 = submit_greenhouse_api(url, profile, resume)

            if result2.get('submitted'):
                applied += 1
                _record_applied(db, company_name, title, url)
                print(f"  ✅ {title} @ {company_name} (retry {attempt})")
                retry_success = True
                break

            # Re-classify in case error changed (e.g. captcha → otp_timeout)
            error2 = result2.get('error', 'unknown')
            error_type2 = classify_error(error2)
            cfg2 = get_retry_config(error_type2)

            if cfg2["strategy"] == STRATEGY.SKIP:
                skipped += 1
                print(f"  ⏭️ {title}: now {error_type2} — skip")
                retry_success = True  # treated as resolved
                break

            if cfg2["strategy"] == STRATEGY.USE_BROWSER:
                job_entry["error_type"] = error_type2
                job_entry["reason"] = error2
                browser_queue.append(job_entry)
                print(f"  🌐 {title}: now {error_type2} → browser queue")
                retry_success = True  # routed, not failed
                break

        if not retry_success:
            failed.append(job_entry)
            company_failures[company_name] = company_failures.get(company_name, 0) + 1
            print(f"  ❌ {title} @ {company_name}: all retries exhausted ({error_type})")

        time.sleep(0.5)

    # ── Strategy 2: Browser batch (Playwright, one session for all queued jobs) ──
    if browser_queue and applied < MAX_APPS:
        remaining = MAX_APPS - applied
        bq_slice = browser_queue[:remaining]
        browser_jobs = [{'url': j['url'], 'title': j['title'], 'company': j['company']}
                        for j in bq_slice]

        print(f"\n🌐 Browser Strategy: {len(browser_jobs)} jobs (Playwright)...")
        try:
            from src.applier import run_applications
            browser_results = run_applications(browser_jobs, dry_run=False,
                                               max_apps=remaining, db=db)

            browser_applied = 0
            submitted_urls: set = set()
            for res in (browser_results or []):
                if res.get('status') == 'submitted' or res.get('submitted'):
                    browser_applied += 1
                    submitted_urls.add(res['url'])
                    _record_applied(db, res.get('company', ''), res.get('title', ''), res['url'])

            applied += browser_applied
            print(f"  🌐 Browser results: {browser_applied} submitted")

            # Jobs browser also failed → save for next run
            for j in bq_slice:
                if j['url'] not in submitted_urls:
                    j['strategy_tried'] = 'api_and_browser'
                    failed.append(j)

            # Jobs we didn't even attempt in browser (exceeded remaining quota)
            failed.extend(browser_queue[remaining:])

        except Exception as browser_err:
            print(f"  ❌ Browser strategy error: {str(browser_err)[:200]}")
            failed.extend(browser_queue)  # save all browser-queued for next run

    else:
        # No browser run — save all browser_queue for next run
        failed.extend(browser_queue)

    # ── Persist remaining failures for next run ──────────────────────────────
    failed_file = 'agent/data/failed_jobs.json'
    existing = load_failed_jobs(failed_file)
    existing.extend(failed)
    save_failed_jobs(failed_file, existing)

    print(f"\n📊 Greenhouse Results:")
    print(f"  ✅ Applied:       {applied}")
    print(f"  ⏭️  Skipped (dedup): {skipped}")
    print(f"  ❌ Failed (retry next run): {len(failed)}")
    if failed:
        by_type: dict = {}
        for j in failed:
            t = j.get('error_type', 'unknown')
            by_type[t] = by_type.get(t, 0) + 1
        for t, count in sorted(by_type.items()):
            print(f"       {t}: {count}")


if __name__ == '__main__':
    main()
