#!/usr/bin/env python3
"""AI Job Application Agent — finds, filters, applies, emails, learns.

Usage:
    python agent.py --cloud      # full pipeline in GitHub Actions
    python agent.py --dry-run    # filter only, no apply/email
    python agent.py --stats      # show dashboard
"""
import argparse, json, os, sqlite3, sys
from datetime import datetime
from pathlib import Path

from src.memory import get_db, init_db, upsert_application, get_applications, get_stats, audit, application_exists, update_application_status
from src.ghost_filter import calculate_ghost_score
from src.ats_detector import detect_ats
from src.job_scout import match_skills
from src.form_filler import load_profile, can_automate_url
from src.email_handler import EmailThrottle, render_template


def run_discover(db, profile):
    """Phase 1: Discover jobs from job-finder pipeline + company portal scanner."""
    all_jobs = []

    # Source 1: Jobs from job-finder pipeline (found_jobs.json)
    from src.bridge import import_jobs_from_finder
    finder_jobs = import_jobs_from_finder("found_jobs.json")
    if finder_jobs:
        all_jobs.extend(finder_jobs)
        print(f"  Phase 1a: {len(finder_jobs)} jobs from job-finder pipeline")

    # Source 2: Direct company career page scanning (Lever + Greenhouse APIs)
    from src.portal_scanner import scan_all_companies, load_companies, discover_company, save_companies
    portal_jobs = scan_all_companies(max_companies=50)
    if portal_jobs:
        all_jobs.extend(portal_jobs)
        print(f"  Phase 1b: {len(portal_jobs)} jobs from company portal scanner")

    # Discover new companies from all jobs found
    if all_jobs:
        companies = load_companies()
        for job in all_jobs:
            company = job.get("company", "")
            if company and len(company) > 2:
                discover_company(company, companies)
        save_companies(companies)

    if not all_jobs:
        print("  Phase 1: No jobs found from any source")

    print(f"  Phase 1 total: {len(all_jobs)} jobs")
    return all_jobs


def run_filter(db, jobs):
    profile = load_profile()
    passed = []
    for job in jobs:
        url = job.get("url", "")
        if not url or application_exists(db, url):
            continue

        # Title filter — only apply to engineering/developer roles
        title_lower = job.get("title", "").lower()
        VALID_TITLES = ["engineer", "developer", "architect", "programmer", "sde", "swe",
                       "software", "java", "backend", "back-end", "back end", "full stack",
                       "fullstack", "devops", "platform", "infrastructure", "cloud",
                       "spring", "microservice", "site reliability", "sre",
                       "tech lead", "api developer", "integration engineer",
                       "systems engineer", "application engineer", "automation engineer",
                       "data engineer", "kafka", "kubernetes"]
        SKIP_TITLES = ["sales", "product manager", "designer", "marketing", "recruiter",
                       "customer success", "account", "rvp", "vp,", "director,", "people",
                       "data governance", "project manager"]
        if any(s in title_lower for s in SKIP_TITLES):
            continue
        if not any(v in title_lower for v in VALID_TITLES):
            continue

        ghost_score, _ = calculate_ghost_score(
            posted_days_ago=job.get("posted_days_ago", 0),
            applicant_count=job.get("applicant_count", 0),
            has_salary=job.get("has_salary", bool(job.get("rate"))),
            description=job.get("description", ""),
        )
        match = match_skills(job.get("description", ""), title=job.get("title", ""))

        if ghost_score > 60:
            print(f"  ⛔ GHOST ({ghost_score}): {job.get('title', '?')}")
            continue
        if match["score"] < 30:
            print(f"  ⚠️  WEAK ({match['score']}%): {job.get('title', '?')}")
            continue

        ats = detect_ats(url)
        job["ats_type"] = ats.ats_type
        job["can_automate"] = ats.can_automate
        job["match_score"] = match["score"]
        job["ghost_score"] = ghost_score

        upsert_application(db, company=job.get("company", ""), job_title=job.get("title", ""),
                           job_url=url, ats_type=ats.ats_type,
                           match_score=match["score"], ghost_score=ghost_score)
        passed.append(job)
        print(f"  ✅ PASS ({match['score']}% match): {job.get('title', '')} @ {job.get('company', '')}")

    print(f"  Phase 2: {len(passed)}/{len(jobs)} passed filter")
    return passed


def run_apply(db, jobs, dry_run=False):
    """Phase 3: Apply to jobs using Playwright.
    
    In cloud mode, only apply to CAPTCHA-free ATS platforms.
    Never crash — report results even if 0 applications succeed.
    """
    CAPTCHA_FREE_ATS = {"lever", "greenhouse", "ashby", "workable"}
    is_cloud = os.environ.get("GITHUB_ACTIONS") == "true"

    automatable = sorted(
        [j for j in jobs if j.get("can_automate", False)],
        key=lambda j: (
            0 if j.get("ats_type") in CAPTCHA_FREE_ATS else 1,
            -j.get("match_score", 0),
        ),
    )

    if is_cloud:
        # CLOUD MODE: only CAPTCHA-free ATS — no unknown sites
        automatable = [j for j in automatable if j.get("ats_type") in CAPTCHA_FREE_ATS]
    else:
        # LOCAL MODE: include unknown sites that aren't blocked
        from urllib.parse import urlparse
        from src.learning_engine import is_blocked_site
        cloud_safe = []
        for j in automatable:
            ats = j.get("ats_type", "unknown")
            if ats in CAPTCHA_FREE_ATS:
                cloud_safe.append(j)
            elif ats == "unknown":
                domain = urlparse(j.get("url", "")).netloc
                if not is_blocked_site(db, domain):
                    cloud_safe.append(j)
        automatable = cloud_safe

    # Diversify: max 2 per domain
    from urllib.parse import urlparse
    seen_domains, diverse = {}, []
    for j in automatable:
        d = urlparse(j.get("url", "")).netloc
        seen_domains[d] = seen_domains.get(d, 0) + 1
        if seen_domains[d] <= 5:
            diverse.append(j)
    automatable = diverse
    email_only = [j for j in jobs if not j.get("can_automate", False)]

    print(f"  Phase 3: {len(automatable)} auto-apply ({'cloud-safe' if is_cloud else 'all'}), {len(email_only)} email-only")

    if not automatable:
        return []

    try:
        from src.applier import run_applications
        results = run_applications(automatable, dry_run=dry_run, max_apps=15, db=db)
    except Exception as e:
        print(f"  ⚠️ Phase 3 crashed (non-fatal): {e}")
        results = []

    # Update DB with results
    for r in results:
        if r.get("status") == "submitted":
            update_application_status(db, r["url"], "applied")
            audit(db, "APPLIED", {"url": r["url"], "company": r.get("company", "")})
        elif r.get("status") == "dry_run":
            audit(db, "DRY_RUN", {"url": r["url"], "fields": r.get("fields_filled", 0)})

    return results


def run_email_report(results, jobs_found, jobs_passed):
    """Phase 4: Email daily report via Resend."""
    resend_key = os.environ.get("RESEND_KEY", "")
    if not resend_key:
        print("  Phase 4: No RESEND_KEY — skipping email report")
        return

    submitted = sum(1 for r in results if r.get("status") in ("submitted", "dry_run"))
    failed = sum(1 for r in results if r.get("status") not in ("submitted", "dry_run"))

    subject = f"🤖 Agent: {submitted} applied, {jobs_found} found — {datetime.now().strftime('%b %d')}"
    body = f"""AI Job Agent Report — {datetime.now().strftime('%A, %B %d %Y')}

Found: {jobs_found} jobs
Passed filter: {jobs_passed}
Applied: {submitted}
Failed: {failed}

Applications:
"""
    for r in results:
        status = "✅" if r.get("status") in ("submitted", "dry_run") else "❌"
        body += f"  {status} {r.get('company', '?')} — {r.get('title', '?')} [{r.get('status')}]\n"

    try:
        import subprocess, tempfile
        payload = json.dumps({
            "from": "Job Agent <onboarding@resend.dev>",
            "to": ["bobrikh75@gmail.com"],
            "subject": subject,
            "text": body,
        })
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(payload)
            tmp = f.name
        subprocess.run(["curl", "-s", "-X", "POST", "https://api.resend.com/emails",
                        "-H", f"Authorization: Bearer {resend_key}",
                        "-H", "Content-Type: application/json",
                        "-d", f"@{tmp}"], capture_output=True, timeout=30)
        os.unlink(tmp)
        print(f"  Phase 4: Report emailed ✅")
    except Exception as e:
        print(f"  Phase 4: Email failed — {e}")


def run_stats(db):
    stats = get_stats(db)
    print("\n📊 Agent Statistics")
    print("─" * 40)
    for key, val in stats.items():
        print(f"  {key:12s}: {val}")


def main():
    parser = argparse.ArgumentParser(description="AI Job Application Agent")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--cloud", action="store_true")
    parser.add_argument("--reset", action="store_true", help="Clear DB for fresh run")
    args = parser.parse_args()

    db = get_db()
    init_db(db)

    if args.reset:
        db.execute("DELETE FROM applications")
        db.execute("DELETE FROM audit_log")
        db.execute("DELETE FROM ats_patterns WHERE ats_type = 'blocked'")
        db.commit()
        print("  🗑️  Database reset")

    if args.stats:
        run_stats(db)
        return

    mode = "cloud" if args.cloud else ("dry_run" if args.dry_run else "interactive")
    print(f"\n🤖 AI Job Agent — {datetime.now().strftime('%Y-%m-%d %H:%M')} [{mode}]")
    print("=" * 50)

    profile = load_profile()
    audit(db, "AGENT_START", {"mode": mode})

    # Phase 1: Discover
    jobs = run_discover(db, profile)

    # Phase 2: Filter
    passed = run_filter(db, jobs) if jobs else []

    # Phase 3: Apply
    results = []
    if passed and not args.dry_run:
        results = run_apply(db, passed, dry_run=False)
    elif passed and args.dry_run:
        results = run_apply(db, passed, dry_run=True)

    # Phase 4: Email report
    if args.cloud or not args.dry_run:
        run_email_report(results, len(jobs), len(passed))

    audit(db, "AGENT_COMPLETE", {"found": len(jobs), "passed": len(passed), "applied": len(results)})
    run_stats(db)


if __name__ == "__main__":
    main()
