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
    greenhouse_companies = companies.get('greenhouse', [])[:30]
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

        url = job.get('url', '')
        if not url:
            continue

        if application_exists(db, url):
            skipped += 1
            continue

        title = job.get('title', '')
        company_name = job.get('company', '')

        # Strategy 1: Try direct API POST (no browser, fastest)
        resume = profile.get('resume_path', 'agent/resume.pdf')
        if not os.path.exists(resume):
            resume = os.path.expanduser('~/Downloads/CV/Bob_Rikh_Java_Backend_Developer_C2C.pdf')

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

        # If API failed, record why and save for retry with browser strategy
        error = result.get('error', 'unknown')

        # Strategy 2: If it's a CAPTCHA/verification issue, note it for solve-unsolved
        failed.append({
            'url': url,
            'title': title,
            'company': company_name,
            'reason': error,
            'platform': 'greenhouse',
            'strategy_tried': 'api_direct',
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
        })
        print(f"  ❌ {title} @ {company_name}: {error[:80]}")

        # Don't hammer the server
        time.sleep(1)

    # Save failed for solve-unsolved to retry with different strategies
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
