"""Bridge between job-finder pipeline and ai-job-agent.

job-finder (find_jobs.py) saves found_jobs.json after each run.
ai-job-agent reads it, applies ghost filter + skill matcher, then acts.

This file goes in BOTH repos:
  - cloud-job-finder/bridge.py (writes found_jobs.json)
  - ai-job-agent/src/bridge.py (reads found_jobs.json)
"""
import json, os
from pathlib import Path
from datetime import datetime

JOBS_FILE = "found_jobs.json"


def export_jobs_for_agent(scored_df, output_path: str = JOBS_FILE):
    """Called by find_jobs.py — exports scored jobs for ai-job-agent to consume."""
    jobs = []
    for _, row in scored_df.iterrows():
        jobs.append({
            "title": str(row.get("title", "")),
            "company": str(row.get("company", "")),
            "url": str(row.get("job_url", "")),
            "location": str(row.get("location", "")),
            "description": str(row.get("description", ""))[:2000],
            "score": int(row.get("score", 0)),
            "is_c2c": bool(row.get("is_c2c", False)),
            "rate": f"${row.get('min_amount', '')}-${row.get('max_amount', '')}/{row.get('interval', '')}"
                    if row.get("min_amount") else "",
            "source": str(row.get("site", "")),
            "found_at": datetime.now().isoformat(),
        })
    with open(output_path, "w") as f:
        json.dump({"jobs": jobs, "exported_at": datetime.now().isoformat(), "count": len(jobs)}, f, indent=2)
    return len(jobs)


def import_jobs_from_finder(input_path: str = JOBS_FILE) -> list[dict]:
    """Called by ai-job-agent — reads jobs exported by find_jobs.py.
    
    Filters out URLs that cannot be auto-applied:
    - LinkedIn job views (require login + bot detection)
    - Indeed company pages (not job applications)
    - Generic aggregator redirects
    """
    if not os.path.exists(input_path):
        return []
    with open(input_path) as f:
        data = json.load(f)
    
    jobs = data.get("jobs", [])
    
    # Filter out unapplicable URLs
    BLOCKED_PATTERNS = [
        "linkedin.com/jobs/",       # Requires login, heavy bot detection
        "linkedin.com/comm/jobs/",  # Same but via comms redirect
        "indeed.com/cmp/",          # Company profile, not a job application
        "indeed.com/viewjob",       # Indeed job view (requires login to apply)
        "indeed.com/jobs?",         # Indeed search results page
        "glassdoor.com/job-listing",  # Requires login
        "glassdoor.com/Job/",       # Same
        "ziprecruiter.com/jobs/",   # Login wall for apply
    ]
    
    filtered = []
    skipped_count = 0
    for job in jobs:
        url = job.get("url", "")
        if any(pattern in url for pattern in BLOCKED_PATTERNS):
            skipped_count += 1
            continue
        if not url or url == "nan":
            skipped_count += 1
            continue
        filtered.append(job)
    
    if skipped_count:
        print(f"  🔗 Bridge: {len(filtered)} usable jobs ({skipped_count} filtered out — LinkedIn/Indeed/aggregator)")
    
    return filtered


def extract_companies_from_jobs(jobs: list[dict]) -> list[str]:
    """Extract unique company names from found jobs for dynamic portal discovery."""
    companies = set()
    for job in jobs:
        company = job.get("company", "").strip()
        if company and company != "nan" and len(company) > 2:
            companies.add(company)
    return sorted(companies)
