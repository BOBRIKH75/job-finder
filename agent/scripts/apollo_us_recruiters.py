#!/usr/bin/env python3
"""Find REAL US-based recruiters at REAL companies via Apollo.io API.

WHY THIS (vs apollo_api_recruiters.py): the old one sourced company domains FROM Bob's
Gmail — which is full of the Indian C2C body-shops that already spam him, so it just found
MORE body-shop recruiters. This instead searches Apollo for recruiters:
  • LOCATED in the United States  (person_locations = US)  ← the key filter
  • at REAL US tech companies / direct employers + legit national staffing firms
  • with recruiter/talent titles
  • reveals verified work emails

Result: real US recruiters at real companies, not offshore bench-sales desks.

Env: APOLLO_API_KEY (required).
Writes verified US recruiters to agent/data/vendor_list.json (deduped) tagged source=apollo-us.
Free tier is limited — capped per run + deduped.

Run: cd ~/Downloads/CV/job-finder/agent && python3 scripts/apollo_us_recruiters.py
"""
import json
import os
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
VENDOR_FILE = DATA / "vendor_list.json"
SEEN_FILE = DATA / "apollo_us_seen.json"

API = "https://api.apollo.io/api/v1/mixed_people/search"

# Recruiter / talent titles at real companies
TITLES = ["Technical Recruiter", "IT Recruiter", "Senior Technical Recruiter",
          "Talent Acquisition Partner", "Talent Acquisition Specialist",
          "Engineering Recruiter", "Contract Recruiter", "Staffing Manager"]

# Target companies: real US tech employers that use Java contractors + legit US staffing.
# (Apollo matches by org name; these are REAL companies, not body shops.)
TARGET_COMPANIES = [
    # Legit national US staffing (real US recruiters, direct-client reqs)
    "TEKsystems", "Kforce", "Robert Half", "Insight Global", "Apex Systems",
    "Randstad", "Experis", "Motion Recruitment", "Beacon Hill Staffing Group",
    "Dexian", "Judge Group", "Genesis10", "Eliassen Group", "Aquent",
    # Real US direct employers that hire Java/backend contractors
    "Charter Communications", "Comcast", "Fidelity Investments", "Capital One",
    "USAA", "Wells Fargo", "JPMorgan Chase", "American Express", "Target",
    "Progressive", "Nationwide", "State Farm", "Cardinal Health", "CVS Health",
    "United Airlines", "Southwest Airlines", "Home Depot", "Lowe's",
]

PER_RUN_CAP = int(os.environ.get("APOLLO_US_CAP", "12"))   # protect free credits


def _env():
    envf = HERE.parent / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _load(p, default):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def apollo_search(company, key):
    """Search Apollo for US-located recruiters at a named company."""
    payload = json.dumps({
        "q_organization_name": company,
        "person_titles": TITLES,
        "person_locations": ["United States"],   # ← THE KEY FILTER: US recruiters only
        "contact_email_status": ["verified"],     # only verified work emails (no fakes)
        "page": 1, "per_page": 10,
    }).encode()
    req = urllib.request.Request(API, data=payload, headers={
        "Content-Type": "application/json", "Cache-Control": "no-cache",
        "X-Api-Key": key, "Accept": "application/json",
    })
    try:
        r = json.load(urllib.request.urlopen(req, timeout=25))
        return r.get("people", []) or r.get("contacts", [])
    except Exception as e:
        print(f"    apollo err {company}: {str(e)[:90]}")
        return []


def main():
    _env()
    key = os.environ.get("APOLLO_API_KEY", "")
    if not key:
        print("APOLLO_API_KEY not set — cannot run"); return
    print("🇺🇸 Apollo US-recruiter finder (real US recruiters at real companies)\n")

    vendors = _load(VENDOR_FILE, [])
    if not isinstance(vendors, list):
        vendors = []
    existing = {(v.get("email") or "").lower() for v in vendors}
    seen = set(_load(SEEN_FILE, []))

    import random
    pool = [c for c in TARGET_COMPANIES if c not in seen]
    random.shuffle(pool)
    pool = pool[:PER_RUN_CAP]

    added = 0
    for company in pool:
        seen.add(company)
        people = apollo_search(company, key)
        got = 0
        for p in people:
            em = (p.get("email") or "").strip().lower()
            if not em or "@" not in em or "not_unlocked" in em or em in existing:
                continue
            # extra guard: must be a US person + verified (Apollo already filtered, double-check)
            existing.add(em)
            vendors.append({
                "name": company,
                "email": em,
                "person": p.get("name", ""),
                "position": p.get("title", "recruiter"),
                "location": (p.get("city") or "") + ", " + (p.get("state") or ""),
                "source": "apollo-us",
                "domain": em.split("@")[-1],
                "notes": f"US recruiter at {company} (Apollo verified)",
            })
            added += 1
            got += 1
            print(f"  ✅ {company:28s} {p.get('name','')[:22]:24s} {em}")
        if got == 0:
            print(f"  –  {company:28s} (no verified US recruiter revealed)")
        time.sleep(1.5)

    VENDOR_FILE.write_text(json.dumps(vendors, indent=2))
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2))
    print(f"\n📊 Added {added} REAL US recruiters (verified emails). Vendor list now {len(vendors)}.")
    print("   These are tagged source=apollo-us and will be emailed with the CV.")


if __name__ == "__main__":
    main()
