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
from src.memory import get_db, init_db, application_exists, upsert_application, claim_job, release_claim

# Git-tracked persistent dedup. Keyed by company+normalized-title, but TIME-WINDOWED:
# a role is "already applied" only for GH_DEDUP_DAYS (default 30). After that it's
# eligible AGAIN, because companies repost / refresh the same req and genuinely new
# postings should be re-applied to. This prevents the "finds 447, applies 0 forever"
# plateau — fresh daily postings and monthly reposts get applied to.
GH_APPLIED_FILE = 'agent/data/greenhouse_applied.json'
GH_DEDUP_DAYS = int(os.environ.get('GH_DEDUP_DAYS', '30'))


def _gh_key(company, title):
    import re as _re
    c = ' '.join((company or '').lower().split())
    t = (title or '').lower()
    # normalize title: drop seniority/paren/loc noise so reposts match
    t = _re.sub(r'\(.*?\)', ' ', t)
    t = _re.sub(r'\b(sr|senior|jr|junior|lead|staff|principal|remote|w2|c2c|contract|us|usa)\b', ' ', t)
    t = ' '.join(_re.sub(r'[^a-z0-9 ]', ' ', t).split())
    return f"{c}|{t}" if c and t else ''


def _load_gh_applied() -> dict:
    """Returns {key: iso_timestamp}. Backward compatible with the old list format
    (list → treated as applied 'long ago' so they expire out of the window)."""
    try:
        raw = json.load(open(GH_APPLIED_FILE))
    except Exception:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        # old format: no timestamps → set to epoch so they're OUTSIDE the dedup
        # window and become eligible again (lets you re-apply to the backlog).
        return {k: '2000-01-01T00:00:00' for k in raw}
    return {}


def _applied_recently(applied: dict, company, title, now) -> bool:
    from datetime import datetime as _dt
    key = _gh_key(company, title)
    if not key or key not in applied:
        return False
    try:
        when = _dt.fromisoformat(str(applied[key]).replace('Z', ''))
    except Exception:
        return True   # malformed → be safe, treat as recent
    return (now - when).days < GH_DEDUP_DAYS


def _save_gh_applied(company, title):
    from datetime import datetime as _dt
    key = _gh_key(company, title)
    if not key:
        return
    applied = _load_gh_applied()
    applied[key] = _dt.utcnow().isoformat()
    # prune entries older than 2x the window to keep the file small
    cutoff_days = GH_DEDUP_DAYS * 2
    pruned = {}
    for k, v in applied.items():
        try:
            if (_dt.utcnow() - _dt.fromisoformat(str(v).replace('Z', ''))).days < cutoff_days:
                pruned[k] = v
        except Exception:
            pruned[k] = v
    try:
        os.makedirs(os.path.dirname(GH_APPLIED_FILE), exist_ok=True)
        json.dump(pruned, open(GH_APPLIED_FILE, 'w'), indent=0)
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
    from datetime import datetime as _dt
    _now = _dt.utcnow()
    _gh_applied = _load_gh_applied()
    _run_seen = set()   # same-run duplicate guard
    print(f"🗂️  {len(_gh_applied)} Greenhouse roles in dedup (window={GH_DEDUP_DAYS}d — older become eligible again)")

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

    # DYNAMIC CV-DRIVEN DISCOVERY — runs AFTER the scan slice is already chosen, so it does
    # NOT disturb THIS run's rotation (the offset stays aligned to the pre-discovery list).
    # New companies are appended to companies.json for FUTURE runs only. Clear, no override:
    #   order = load → rotate/pick(this run) → discover(future runs) → scan(picked) → apply.
    # Runs only every Nth run (GH_DISCOVER_EVERY, default 3) to avoid hammering job-search
    # (which shares the reCAPTCHA rate-limit). GH_DISCOVER=0 disables entirely.
    if os.environ.get('GH_DISCOVER', '1') == '1' and (_offset // max(_scan_count, 1)) % \
            int(os.environ.get('GH_DISCOVER_EVERY', '3')) == 0:
        try:
            from src.portal_scanner import discover_company, save_companies
            _before = len(companies.get('greenhouse', []))
            _names = set()
            try:
                from jobspy import scrape_jobs as _sj
                # Rotate through diverse discovery terms so each cycle surfaces
                # companies from a DIFFERENT slice (domains/seniority/work-type),
                # not just the same 2. Pick 3 per run based on scan offset.
                _disc_pool = [
                    os.environ.get('GH_DISCOVER_TERM', 'Java Spring Boot developer remote'),
                    'Senior Java backend engineer remote',
                    'Java microservices engineer',
                    'Java developer fintech',
                    'Java developer healthcare',
                    'Java AWS Kafka engineer',
                    'Java full stack developer hybrid',
                    'Java software engineer contract',
                ]
                _di = (_offset // max(_scan_count, 1)) % len(_disc_pool)
                _disc_terms = [_disc_pool[(_di + k) % len(_disc_pool)] for k in range(3)]
                for _q in _disc_terms:
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
            for _cn in sorted(_names)[:60]:
                discover_company(_cn, companies)   # only APPENDS new boards; never removes
            _after = len(companies.get('greenhouse', []))
            if _after > _before:
                save_companies(companies)   # persists to git-tracked companies.json (future runs)
                print(f"  🔍 CV-driven discovery: +{_after - _before} new Greenhouse boards "
                      f"(now {_after}, available NEXT run — this run's rotation unchanged)")
            else:
                print(f"  🔍 CV-driven discovery: no new boards this run")
        except Exception as _de:
            print(f"  ⚠️ discovery step error: {str(_de)[:60]} — continuing")

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
        # Time-windowed dedup: skip only if this role was applied within GH_DEDUP_DAYS,
        # OR already handled in THIS run, OR this exact posting URL is already applied.
        # New postings (new URL) + roles last applied >window-days-ago are NOT skipped,
        # so fresh daily jobs and monthly reposts get applied to.
        _k = _gh_key(company_name, title)
        if (_k and _k in _run_seen) \
                or _applied_recently(_gh_applied, company_name, title, _now) \
                or application_exists(db, url):   # URL-only = exact same posting
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

        # DB-LEVEL ATOMIC CLAIM (Bobur's idea): claim this company+title before applying.
        # If a concurrent run (local + CI overlap) already claimed it, skip — only ONE
        # run can win the claim (UNIQUE + INSERT OR IGNORE). Prevents concurrent double-apply
        # that the in-memory set alone can't (different processes). Released on hard failure.
        if not claim_job(db, company_name, title):
            skipped += 1
            print(f"  🔒 already claimed by another run — skipping ({title[:35]} @ {company_name[:20]})")
            continue

        # ── Strategy 1: Direct API POST ──────────────────────────────────────
        result = submit_greenhouse_api(url, profile, resume)

        if result.get('submitted'):
            applied += 1
            _record_applied(db, company_name, title, url)
            if _k:
                _run_seen.add(_k)   # same-run duplicate guard
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
            release_claim(db, company_name, title)   # not applied → free the claim
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
                _k2=_gh_key(company_name, title);  _run_seen.add(_k2) if _k2 else None   # same-run dup guard
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
                    _k3=_gh_key(res.get('company',''), res.get('title',''));  _run_seen.add(_k3) if _k3 else None   # same-run dup

            applied += browser_applied
            print(f"  🌐 Browser results: {browser_applied} submitted")

            # Jobs browser also failed → save for next run
            for j in bq_slice:
                if j['url'] not in submitted_urls:
                    j['strategy_tried'] = 'api_and_browser'
                    failed.append(j)
                    release_claim(db, j.get('company', ''), j.get('title', ''))   # not applied → free claim

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
