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
from src.bridge import import_jobs_from_finder


def run_discover(db, profile):
    jobs = import_jobs_from_finder("found_jobs.json")
    if jobs:
        print(f"  Phase 1: Loaded {len(jobs)} jobs from job-finder pipeline")
    else:
        print("  Phase 1: No found_jobs.json — waiting for job-finder to run")
    return jobs


def run_filter(db, jobs):
    profile = load_profile()
    passed = []
    for job in jobs:
        url = job.get("url", "")
        if not url or application_exists(db, url):
            continue

        ghost_score, _ = calculate_ghost_score(
            posted_days_ago=job.get("posted_days_ago", 0),
            applicant_count=job.get("applicant_count", 0),
            has_salary=job.get("has_salary", bool(job.get("rate"))),
            description=job.get("description", ""),
        )
        match = match_skills(job.get("description", ""))

        if ghost_score > 60:
            print(f"  ⛔ GHOST ({ghost_score}): {job.get('title', '?')}")
            continue
        if match["score"] < 40:
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
    """Phase 3: Actually apply to jobs using Playwright."""
    automatable = [j for j in jobs if j.get("can_automate", False)]
    email_only = [j for j in jobs if not j.get("can_automate", False)]

    print(f"  Phase 3: {len(automatable)} auto-apply, {len(email_only)} email-only")

    if not automatable:
        return []

    from src.applier import run_applications
    results = run_applications(automatable, dry_run=dry_run, max_apps=10)

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
    args = parser.parse_args()

    db = get_db()
    init_db(db)

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
