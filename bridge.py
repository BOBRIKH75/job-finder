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
        # Prefer company career page URL over LinkedIn (agent can apply to company pages)
        url = str(row.get("job_url", ""))
        company_url = str(row.get("company_url", ""))
        if company_url and company_url != "nan" and company_url.startswith("http") and "linkedin.com" not in company_url:
            url = company_url  # Direct company apply page (Lever, Greenhouse, etc)
        
        jobs.append({
            "title": str(row.get("title", "")),
            "company": str(row.get("company", "")),
            "url": url,
            "linkedin_url": str(row.get("job_url", "")) if "linkedin" in str(row.get("job_url", "")) else "",
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
    """Called by ai-job-agent — reads jobs exported by find_jobs.py."""
    if not os.path.exists(input_path):
        return []
    with open(input_path) as f:
        data = json.load(f)
    return data.get("jobs", [])


def export_missed_job(title, company, url, source, location="", score=40,
                      is_c2c=False, rate="", jobs_file: str = None):
    """Add a job the bot could NOT auto-apply to → found_jobs.json (the manual list).

    Called by dice/indeed/greenhouse apply scripts at their 'not applied' point so
    EVERY channel's misses land in Bob's manual-apply list. Deduped by URL. Safe:
    resolves the file whether run from repo root or agent/, never raises.
    """
    if not url or not title:
        return False
    # Always target the repo-root found_jobs.json (next to this bridge.py),
    # regardless of the caller's working directory (dice runs from agent/).
    path = jobs_file or os.path.join(os.path.dirname(os.path.abspath(__file__)), JOBS_FILE)
    try:
        data = {"jobs": [], "count": 0}
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
        jobs = data.get("jobs", [])
        if any(j.get("url") == url for j in jobs):
            return False  # already listed
        jobs.append({
            "title": str(title), "company": str(company or "?"), "url": str(url),
            "linkedin_url": str(url) if "linkedin" in str(url) else "",
            "location": str(location or "Remote"), "description": "",
            "score": int(score or 40), "is_c2c": bool(is_c2c), "rate": str(rate or ""),
            "source": str(source), "found_at": datetime.now().isoformat(),
        })
        data["jobs"] = jobs
        data["count"] = len(jobs)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False
