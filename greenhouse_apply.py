#!/usr/bin/env python3
"""Dedicated Greenhouse applicator — handles email verification + reCAPTCHA.

Strategy per job:
1. Try direct API POST first (greenhouse_api.py) — fastest, no browser
2. If 400/422 → try browser with form filling
3. If email verification required → read code from Gmail (email_code_reader.py)
4. If reCAPTCHA → try Gemini solver
5. If still fails → save to data/failed_jobs.json with reason for solve-unsolved
"""
import json
import os
import sys
import time
import random

# Force unbuffered output so CI shows progress in real-time
os.environ['PYTHONUNBUFFERED'] = '1'
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

sys.path.insert(0, 'agent')

from src.portal_scanner import scan_greenhouse, load_companies
from src.greenhouse_api import submit_greenhouse_api
from src.form_filler import load_profile
from src.email_code_reader import get_verification_code
from src.memory import get_db, init_db, application_exists, upsert_application


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
    companies = load_companies()

    # Scan top 30 Greenhouse companies for open Java jobs
    all_jobs = []
    greenhouse_companies = companies.get('greenhouse', [])
    random.shuffle(greenhouse_companies)  # Don't always try same companies first
    greenhouse_companies = greenhouse_companies[:15]
    print(f"🔍 Scanning {len(greenhouse_companies)} Greenhouse companies...")

    for company in greenhouse_companies:
        try:
            jobs = scan_greenhouse(company)
            all_jobs.extend(jobs)
        except Exception as e:
            print(f"  ⚠️ {company}: {str(e)[:60]}")
        time.sleep(0.3)

    print(f"Found {len(all_jobs)} Greenhouse jobs matching skills")

    applied = 0
    failed = []
    skipped = 0
    MAX_APPS = 30

    for job in all_jobs:
        if applied >= MAX_APPS:
            break
        
        # Don't waste time on API attempts that always fail — limit to 30 attempts total
        # so browser batch gets time to run within the 35-min timeout
        if len(failed) >= MAX_APPS:
            print(f"  ⚡ {len(failed)} API failures → skipping rest, moving to browser batch")
            break

        url = job.get('url', '')
        if not url:
            continue

        if application_exists(db, url):
            skipped += 1
            continue

        title = job.get('title', '')
        company_name = job.get('company', '')

        # Strategy 1: Try direct API POST (no browser, fastest)
        # Resume must work on both: local dev AND self-hosted runner (different users/paths)
        # The ONLY reliable path is relative to this script or GITHUB_WORKSPACE
        script_dir = os.path.dirname(os.path.abspath(__file__))
        resume_candidates = [
            os.path.join(script_dir, 'agent', 'resume.pdf'),          # from repo root
            os.path.join(script_dir, '..', 'agent', 'resume.pdf'),    # from subdir
            'agent/resume.pdf',                                        # CWD = repo root
            'resume.pdf',                                              # CWD = agent/
            os.path.expanduser('~/Downloads/CV/Bob_Rikh_Java_Backend_Developer_C2C.pdf'),
            os.path.expanduser('~/Downloads/CV/job-finder/agent/resume.pdf'),
        ]
        resume = profile.get('resume_path', '')
        if not resume or not os.path.exists(resume):
            resume = next((r for r in resume_candidates if os.path.exists(r)), 'agent/resume.pdf')
        
        # Debug: show which resume path was resolved
        if applied == 0 and len(failed) == 0 and skipped == 0:
            print(f"  📁 Resume resolved to: {resume} (exists: {os.path.exists(resume)})")
            print(f"  📁 CWD: {os.getcwd()}")
            print(f"  📁 script_dir: {script_dir}")

        result = submit_greenhouse_api(url, profile, resume)

        if result.get('submitted'):
            applied += 1
            upsert_application(
                db,
                company=company_name,
                job_title=title,
                job_url=url,
                ats_type='greenhouse',
                match_score=80,
                status='applied',
            )
            print(f"  ✅ {title} @ {company_name} (API)")
            time.sleep(1)
            continue

        # If API failed, collect for browser batch (don't open browser for each job!)
        error = result.get('error', 'unknown')
        
        if 'HTTP 400' in error or 'HTTP 422' in error or 'Bad Request' in error:
            # Save for browser batch below
            failed.append({
                'url': url,
                'title': title,
                'company': company_name,
                'reason': error,
                'platform': 'greenhouse',
                'strategy_tried': 'api_only',
                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            })
            print(f"  ⏳ {title} @ {company_name}: API 400 → queued for browser")
        else:
            failed.append({
                'url': url,
                'title': title,
                'company': company_name,
                'reason': error,
                'platform': 'greenhouse',
                'strategy_tried': 'api_only',
                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            })
            print(f"  ❌ {title} @ {company_name}: {error[:80]}")

        time.sleep(0.5)

    # === STRATEGY 2: Browser batch (open Playwright ONCE for all API-failed jobs) ===
    browser_queue = [j for j in failed if 'HTTP 400' in j.get('reason', '') or 'Bad Request' in j.get('reason', '')]
    
    if browser_queue and applied < MAX_APPS:
        remaining = MAX_APPS - applied
        browser_jobs = [{'url': j['url'], 'title': j['title'], 'company': j['company']} for j in browser_queue[:remaining]]
        
        print(f"\n🌐 Browser Strategy: {len(browser_jobs)} jobs (Playwright, one browser session)...")
        try:
            from src.applier import run_applications
            browser_results = run_applications(browser_jobs, dry_run=False, max_apps=remaining, db=db)
            
            browser_applied = 0
            for res in (browser_results or []):
                if res.get('submitted'):
                    browser_applied += 1
                    upsert_application(
                        db,
                        company=res.get('company', ''),
                        job_title=res.get('title', ''),
                        job_url=res.get('url', ''),
                        ats_type='greenhouse',
                        match_score=80,
                        status='applied',
                    )
            applied += browser_applied
            print(f"  🌐 Browser results: {browser_applied} submitted")
            
            # Remove successfully submitted from failed list
            submitted_urls = {r['url'] for r in (browser_results or []) if r.get('submitted')}
            failed = [f for f in failed if f['url'] not in submitted_urls]
            
        except Exception as browser_err:
            print(f"  ❌ Browser strategy error: {str(browser_err)[:100]}")

    # Save remaining failed for solve-unsolved to retry
    failed_file = 'agent/data/failed_jobs.json'
    existing = load_failed_jobs(failed_file)
    existing.extend(failed)
    save_failed_jobs(failed_file, existing)

    print(f"\n📊 Greenhouse Results:")
    print(f"  ✅ Applied: {applied}")
    print(f"  ❌ Failed:  {len(failed)} (saved for retry)")
    print(f"  ⏭️ Skipped: {skipped} (already applied)")


if __name__ == '__main__':
    main()
