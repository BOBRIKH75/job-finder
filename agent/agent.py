#!/usr/bin/env python3
"""AI Job Application Agent — main entry point.

Pipeline: discover → filter → apply → email → learn

Usage:
    python agent.py                  # interactive mode
    python agent.py --dry-run        # find + filter only, no apply/email
    python agent.py --stats          # show dashboard stats
"""
import argparse, json, sqlite3, sys
from datetime import datetime
from pathlib import Path

from src.memory import get_db, init_db, upsert_application, get_applications, get_stats, audit, application_exists
from src.ghost_filter import calculate_ghost_score
from src.ats_detector import detect_ats
from src.job_scout import match_skills, extract_rate, is_remote, is_c2c
from src.form_filler import load_profile, can_automate_url
from src.email_handler import EmailThrottle
from src.bridge import import_jobs_from_finder

CONFIG_PATH = Path(__file__).parent / "config" / "config.yaml"


def load_config() -> dict:
    """Load YAML config (simple parser, no pyyaml dependency)."""
    text = CONFIG_PATH.read_text()
    # Minimal YAML-like parsing for flat/nested keys
    config = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" in stripped and not stripped.endswith(":"):
            key, val = stripped.split(":", 1)
            val = val.strip().strip('"').strip("'")
            if val.isdigit():
                val = int(val)
            elif val.replace(".", "", 1).isdigit():
                val = float(val)
            elif val.lower() in ("true", "false"):
                val = val.lower() == "true"
            config[key.strip()] = val
    return config


def run_discover(db: sqlite3.Connection, profile: dict, dry_run: bool = False) -> list[dict]:
    """Phase 1: Discover jobs from job-finder pipeline or local file."""
    jobs = import_jobs_from_finder("found_jobs.json")
    if jobs:
        print(f"  Phase 1: Loaded {len(jobs)} jobs from job-finder pipeline")
    else:
        print("  Phase 1: No found_jobs.json — waiting for job-finder pipeline to run")
    return jobs


def run_filter(db: sqlite3.Connection, jobs: list[dict]) -> list[dict]:
    """Phase 2: Filter ghost jobs and score matches."""
    profile = load_profile()
    passed = []
    for job in jobs:
        if application_exists(db, job.get("url", "")):
            continue
        ghost_score, signals = calculate_ghost_score(
            posted_days_ago=job.get("posted_days_ago", 0),
            applicant_count=job.get("applicant_count", 0),
            has_salary=job.get("has_salary", False),
            description=job.get("description", ""),
            has_named_contact=job.get("has_named_contact", False),
        )
        match = match_skills(job.get("description", ""))
        job["ghost_score"] = ghost_score
        job["match_score"] = match["score"]
        job["matched_skills"] = match["matched"]
        job["verdict"] = match["verdict"]

        if ghost_score > 60:
            print(f"  ⛔ GHOST ({ghost_score}): {job.get('title', '?')} @ {job.get('company', '?')}")
            continue
        if match["score"] < 40:
            print(f"  ⚠️  WEAK ({match['score']}%): {job.get('title', '?')}")
            continue

        ats = detect_ats(job.get("url", ""))
        job["ats_type"] = ats.ats_type
        job["can_automate"] = ats.can_automate

        upsert_application(db, company=job.get("company", ""), job_title=job.get("title", ""),
                           job_url=job["url"], ats_type=ats.ats_type,
                           match_score=match["score"], ghost_score=ghost_score)
        passed.append(job)
        print(f"  ✅ PASS ({match['score']}% match, ghost={ghost_score}): {job.get('title', '')} @ {job.get('company', '')}")

    print(f"  Phase 2: {len(passed)}/{len(jobs)} jobs passed filter")
    return passed


def run_stats(db: sqlite3.Connection):
    """Show agent statistics."""
    stats = get_stats(db)
    print("\n📊 Agent Statistics")
    print("─" * 40)
    for key, val in stats.items():
        print(f"  {key:12s}: {val}")
    recent = get_applications(db, limit=5)
    if recent:
        print(f"\n📋 Recent Applications (last 5)")
        print("─" * 60)
        for app in recent:
            print(f"  {app['company']:20s} | {app['job_title']:25s} | {app['status']}")


def main():
    parser = argparse.ArgumentParser(description="AI Job Application Agent")
    parser.add_argument("--dry-run", action="store_true", help="Find + filter only, no apply/email")
    parser.add_argument("--stats", action="store_true", help="Show dashboard stats")
    parser.add_argument("--cloud", action="store_true", help="Cloud mode — headless browser, no laptop needed")
    args = parser.parse_args()

    db = get_db()
    init_db(db)

    if args.stats:
        run_stats(db)
        return

    print(f"\n🤖 AI Job Agent — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    mode = "cloud" if args.cloud else ("dry_run" if args.dry_run else "interactive")
    profile = load_profile()
    audit(db, "AGENT_START", {"mode": mode})

    if args.cloud:
        print("  ☁️  Cloud mode — headless browser, no laptop needed")

    # Phase 1: Discover
    jobs = run_discover(db, profile, args.dry_run)

    # Phase 2: Filter
    if jobs:
        passed = run_filter(db, jobs)
    else:
        print("  No new jobs to process. Use Dice MCP or add jobs manually.")

    # Phase 3-5: Apply, Email, Learn (future — requires browser-use + Ollama)
    if not args.dry_run:
        print("\n  Phase 3-5: Apply → Email → Learn (connect browser-use + Ollama)")

    audit(db, "AGENT_COMPLETE", {"jobs_found": len(jobs), "mode": mode})
    run_stats(db)


if __name__ == "__main__":
    main()
