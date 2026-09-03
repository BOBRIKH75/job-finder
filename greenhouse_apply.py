#!/usr/bin/env python3
"""Dedicated Greenhouse applicator — handles email verification + reCAPTCHA.

Healing levels:
  Level 1 (per-job): classify error → skip / retry_api / use_browser
  Level 2 (DeepHeal): after all retries exhausted →
    - mark company as browser_only if API always fails
    - patch missing form field answers into DB so Playwright fills them next attempt
    - re-queue job with patch applied for one final browser attempt
  Level 3: if still failing → save to failed_jobs.json with full diagnostic
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
from src.self_heal import classify_error, get_retry_config, STRATEGY, DeepHeal
from src.memory import get_db, init_db, application_exists, upsert_application

# Git-tracked persistent dedup (Bobur: same company+title kept repeating). The DB is
# cache-only in CI (lossy) and near-empty locally, so we ALSO keep a JSON keyed by
# company+normalized-title. Committed by CI → survives across runs on local AND CI.
GH_APPLIED_FILE = 'agent/data/greenhouse_applied.json'


def _gh_key(company, title):
    import re as _re
    c = ' '.join((company or '').lower().split())
    t = (title or '').lower()
    # normalize title: drop seniority/paren/loc noise so reposts match
    t = _re.sub(r'\(.*?\)', ' ', t)
    t = _re.sub(r'\b(sr|senior|jr|junior|lead|staff|principal|remote|w2|c2c|contract|us|usa)\b', ' ', t)
    t = ' '.join(_re.sub(r'[^a-z0-9 ]', ' ', t).split())
    return f"{c}|{t}" if c and t else ''


def _load_gh_applied() -> set:
    try:
        return set(json.load(open(GH_APPLIED_FILE)))
    except Exception:
        return set()


def _save_gh_applied(company, title):
    key = _gh_key(company, title)
    if not key:
        return
    s = _load_gh_applied(); s.add(key)
    try:
        os.makedirs(os.path.dirname(GH_APPLIED_FILE), exist_ok=True)
        json.dump(sorted(s), open(GH_APPLIED_FILE, 'w'), indent=0)
    except Exception:
        pass


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
    _save_gh_applied(company, title)   # persist to git-tracked JSON (survives CI runs)


def main():
    db = get_db()
    init_db(db)
    profile = load_profile()
    companies = load_companies()
    _gh_applied = _load_gh_applied()
    print(f"🗂️  {len(_gh_applied)} Greenhouse company+title already applied (persistent dedup)")

    # DYNAMIC CV-DRIVEN DISCOVERY (Bobur: find NEW companies based on my CV, not a static
    # list). Search job boards for Java/Spring roles, extract the hiring company names, probe
    # each for a real Greenhouse/Lever board, and add the ones that exist. The list then
    # GROWS over time (companies.json is git-tracked + CI-committed). GH_DISCOVER=0 disables.
    if os.environ.get('GH_DISCOVER', '1') == '1':
        try:
            _before = len(companies.get('greenhouse', []))
            from src.portal_scanner import discover_company, save_companies
            _names = set()
            try:
                from jobspy import scrape_jobs as _sj
                for _q in (os.environ.get('GH_DISCOVER_TERM',
                           'Java Spring Boot developer remote'),
                           'Senior Java backend engineer remote',
                           'Java microservices developer remote'):
                    try:
                        _df = _sj(site_name=['indeed', 'linkedin'], search_term=_q,
                                  location='USA', results_wanted=25)
                        if _df is not None and not getattr(_df, 'empty', True) and 'company' in _df.columns:
                            for _c in _df['company'].tolist():
                                _c = str(_c).strip()
                                if _c and _c.lower() != 'nan' and len(_c) > 2:
                                    _names.add(_c)
                    except Exception as _qe:
                        print(f"  ⚠️ discover search '{_q[:30]}' err: {str(_qe)[:40]}")
            except Exception:
                print("  ⚠️ jobspy unavailable for discovery — skipping")
            _probed = 0
            for _cn in sorted(_names)[:60]:   # cap probes per run
                discover_company(_cn, companies)
                _probed += 1
            _after = len(companies.get('greenhouse', []))
            if _after > _before:
                save_companies(companies)
                print(f"  🔍 CV-driven discovery: probed {_probed} companies from Java/Spring "
                      f"searches → +{_after - _before} new Greenhouse boards (now {_after})")
            else:
                print(f"  🔍 CV-driven discovery: probed {_probed}, no new boards this run")
        except Exception as _de:
            print(f"  ⚠️ discovery step error: {str(_de)[:60]} — continuing with existing list")

    greenhouse_companies = companies.get('greenhouse', [])
    # ROTATE through ALL companies (Bobur: kept hitting the SAME companies). random.shuffle
    # + [:15] re-picked the same popular ~15 by chance and never covered the full list.
    # Use round-robin: each run scans the NEXT slice (offset advances + persists), so over
    # several runs we cover all 95. Slice size via GH_SCAN_COUNT (default 15).
    from src.portal_scanner import _load_scan_offset, _save_scan_offset, _rotate
    _scan_count = int(os.environ.get('GH_SCAN_COUNT', '15'))
    _total = len(greenhouse_companies)
    _offset = _load_scan_offset()
    # sort for a STABLE order (so the offset means the same slice every time), then rotate
    greenhouse_companies = sorted(set(greenhouse_companies))
    picked = _rotate(greenhouse_companies, _offset, _scan_count)
    # advance offset for next run (wraps around the full list)
    if _total:
        _save_scan_offset((_offset + _scan_count) % _total)
    greenhouse_companies = picked
    print(f"🔍 Scanning {len(greenhouse_companies)} of {_total} Greenhouse companies "
          f"(offset {_offset} → {( _offset + _scan_count) % max(_total,1)}, round-robin covers all)")

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

    companies_file = 'agent/data/companies.json'
    healer = DeepHeal(db, companies_file, browser_queue)

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
        title = job.get('title', '')
        company_name = job.get('company', '')

        # DEDUP FIX (Bobur: same company+title kept repeating): check by URL AND by
        # company+title. Greenhouse re-posts the same role under a NEW url/gh_jid, so a
        # URL-only check let duplicates through. Passing company+title uses the
        # normalized-title fallback in application_exists() to catch re-postings.
        # ALSO check the git-tracked JSON set (survives CI runs; DB is cache-only/lossy).
        if _gh_key(company_name, title) in _gh_applied or \
                application_exists(db, url, company=company_name, title=title):
            skipped += 1
            continue

        # CV-FIT GATE (Bobur: only apply to jobs that MATCH the CV — Java/Spring/
        # backend/remote/C2C — don't waste time on off-target roles). Same matcher as
        # Indeed. scan_greenhouse's matches_skills() is broad (any 1 keyword); this is
        # the strict gate with hard-negatives (.net/salesforce/nurse/frontend-only...).
        # CV_MATCH_OFF=1 disables. Uses title + description if available.
        if os.environ.get('CV_MATCH_OFF') != '1':
            try:
                from src.cv_match import should_apply as _cv_ok
            except Exception:
                _cv_ok = None
            if _cv_ok is not None:
                _desc = job.get('description', '') or ''
                _loc = job.get('location', '') or ''
                _ok, _score, _why = _cv_ok(title, _desc, _loc)
                if not _ok:
                    skipped += 1
                    print(f"  ⏭️ off-CV: '{title[:40]}' @ {company_name[:20]} "
                          f"(score={_score} {','.join(_why)})")
                    continue

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
            # ── Level 2: DeepHeal — try to patch and re-queue ────────────────
            deep_fixed = healer.attempt(job_entry, error_type, error)
            if not deep_fixed:
                # Level 3: truly unresolvable — save with full diagnostic
                job_entry["deep_investigated"] = True
                failed.append(job_entry)
                company_failures[company_name] = company_failures.get(company_name, 0) + 1
                print(f"  ❌ {title} @ {company_name}: all levels exhausted ({error_type})")

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
