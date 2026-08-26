#!/usr/bin/env python3
"""Auto-discover C2C recruiters from multiple sources.

Sources:
1. nvoids.com — scrape Java C2C job posts, extract recruiter emails
2. Google Groups — extract recruiter emails from C2C requirement posts
3. Snov.io API — find emails by name + company (from LinkedIn profiles)
4. Hunter.io API — domain search for recruiter emails at staffing companies

Run daily. Saves new contacts to data/vendor_list.json.
Deduplicates by email. Never contacts same person twice.
"""
import json, os, re, time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

# API Keys
HUNTER_KEY = os.environ.get("HUNTER_API_KEY", "")
SNOV_USER_ID = os.environ.get("SNOV_USER_ID", "")
SNOV_SECRET = os.environ.get("SNOV_API_SECRET", "")

VENDOR_FILE = Path(__file__).parent.parent / "data" / "vendor_list.json"
HISTORY_FILE = Path(__file__).parent.parent / "data" / "recruiter_discovery_log.json"

# Email regex
EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

# C2C staffing companies to search recruiters at (via Hunter domain search)
TARGET_DOMAINS = [
    "consultadd.com", "collabera.com", "mastechdigital.com",
    "pyramidci.com", "diverselynx.com", "talentburst.com",
    "vdart.com", "skiltrek.com", "xoriant.com",
    "inspyrsolutions.com", "motionrecruitment.com",
    "tier2tek.com", "itechus.net", "srlsoft.com",
    "ibridgetechsoft.com", "multivision-inc.com",
    "spruceinfotech.com", "avanciers.com", "esolutions.com",
]


def load_vendors() -> list:
    if VENDOR_FILE.exists():
        return json.loads(VENDOR_FILE.read_text())
    return []


def save_vendors(vendors: list):
    VENDOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    VENDOR_FILE.write_text(json.dumps(vendors, indent=2))


def get_existing_emails(vendors: list) -> set:
    return {v.get("email", "").lower() for v in vendors}


# === SOURCE 1: nvoids.com ===
def scrape_nvoids() -> list:
    """Scrape nvoids.com for Java C2C job postings with recruiter emails."""
    found = []
    try:
        # nvoids has a search API
        resp = requests.get(
            "https://jobs.nvoids.com/search_jobs.jsp",
            params={"keyword": "Java C2C", "days": "7"},
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        if resp.status_code == 200:
            # Extract emails from the page
            emails = EMAIL_RE.findall(resp.text)
            # Filter out common non-recruiter emails
            skip = {"admin@", "support@", "noreply@", "no-reply@", "info@nvoids", "job_kill"}
            for email in set(emails):
                if not any(s in email.lower() for s in skip):
                    found.append({
                        "name": "",
                        "company": email.split("@")[1].split(".")[0].title(),
                        "email": email.lower(),
                        "source": "nvoids.com",
                        "verified": datetime.now().strftime("%Y-%m-%d"),
                    })
    except Exception as e:
        print(f"  nvoids error: {e}")
    return found


# === SOURCE 2: Google Groups ===
def scrape_google_groups() -> list:
    """Extract recruiter emails from C2C Google Groups (public RSS feeds)."""
    found = []
    groups = [
        "c2chotlist-requirement-posting",
        "only-c2c-req",
        "c2c-w2--requirements",
        "C2C-Corp2Corp-Jobs",
    ]
    for group in groups:
        try:
            # Google Groups RSS feed
            url = f"https://groups.google.com/g/{group}/feed"
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                emails = EMAIL_RE.findall(resp.text)
                skip = {"admin@", "support@", "noreply@", "no-reply@", "google.com"}
                for email in set(emails):
                    if not any(s in email.lower() for s in skip):
                        found.append({
                            "name": "",
                            "company": email.split("@")[1].split(".")[0].title(),
                            "email": email.lower(),
                            "source": f"groups.google.com/{group}",
                            "verified": datetime.now().strftime("%Y-%m-%d"),
                        })
            time.sleep(1)
        except Exception as e:
            print(f"  group {group} error: {e}")
    return found


# === SOURCE 3: Hunter.io Domain Search ===
def search_hunter(domain: str) -> list:
    """Find recruiter emails at a company via Hunter.io."""
    if not HUNTER_KEY:
        return []
    found = []
    try:
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={
                "domain": domain,
                "type": "personal",
                "department": "human_resources",
                "limit": 5,
                "api_key": HUNTER_KEY,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            for e in data.get("emails", []):
                found.append({
                    "name": f"{e.get('first_name', '')} {e.get('last_name', '')}".strip(),
                    "company": data.get("organization", domain),
                    "email": e["value"].lower(),
                    "position": e.get("position", ""),
                    "linkedin": e.get("linkedin", ""),
                    "source": f"hunter.io/{domain}",
                    "verified": datetime.now().strftime("%Y-%m-%d"),
                    "confidence": e.get("confidence", 0),
                })
    except Exception as e:
        print(f"  hunter {domain} error: {e}")
    return found


# === SOURCE 4: Snov.io Email Finder ===
def get_snov_token() -> Optional[str]:
    """Get Snov.io access token."""
    if not SNOV_USER_ID or not SNOV_SECRET:
        return None
    try:
        resp = requests.post(
            "https://api.snov.io/v1/oauth/access_token",
            json={"grant_type": "client_credentials", "client_id": SNOV_USER_ID, "client_secret": SNOV_SECRET},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
    except Exception:
        pass
    return None


def search_snov_by_domain(domain: str, token: str) -> list:
    """Find emails at a domain via Snov.io."""
    found = []
    try:
        resp = requests.post(
            "https://api.snov.io/v2/domain-emails-with-info",
            json={"domain": domain, "limit": 5, "type": "personal", "access_token": token},
            timeout=10,
        )
        if resp.status_code == 200:
            for e in resp.json().get("emails", []):
                found.append({
                    "name": f"{e.get('firstName', '')} {e.get('lastName', '')}".strip(),
                    "company": domain,
                    "email": e.get("email", "").lower(),
                    "position": e.get("position", ""),
                    "source": f"snov.io/{domain}",
                    "verified": datetime.now().strftime("%Y-%m-%d"),
                })
    except Exception as e:
        print(f"  snov {domain} error: {e}")
    return found


def main():
    print("🔍 Recruiter Finder — searching for real C2C recruiters...\n")
    vendors = load_vendors()
    existing = get_existing_emails(vendors)
    all_new = []

    # Source 1: nvoids.com
    print("📡 Source 1: nvoids.com (Java C2C hotlist)...")
    nvoids = scrape_nvoids()
    new_nvoids = [v for v in nvoids if v["email"] not in existing]
    all_new.extend(new_nvoids)
    existing.update(v["email"] for v in new_nvoids)
    print(f"  Found {len(nvoids)} emails, {len(new_nvoids)} new\n")

    # Source 2: Google Groups
    print("📡 Source 2: Google Groups (4 C2C groups)...")
    groups = scrape_google_groups()
    new_groups = [v for v in groups if v["email"] not in existing]
    all_new.extend(new_groups)
    existing.update(v["email"] for v in new_groups)
    print(f"  Found {len(groups)} emails, {len(new_groups)} new\n")

    # Source 3: Hunter.io (top 5 domains to stay within free tier)
    if HUNTER_KEY:
        print("📡 Source 3: Hunter.io (domain search)...")
        for domain in TARGET_DOMAINS[:5]:  # 5 searches per run (25/month free)
            results = search_hunter(domain)
            new_results = [v for v in results if v["email"] not in existing]
            all_new.extend(new_results)
            existing.update(v["email"] for v in new_results)
            if new_results:
                print(f"  {domain}: {len(new_results)} new contacts")
            time.sleep(1)
        print()

    # Source 4: Snov.io
    snov_token = get_snov_token()
    if snov_token:
        print("📡 Source 4: Snov.io (domain emails)...")
        for domain in TARGET_DOMAINS[5:10]:  # Next 5 domains
            results = search_snov_by_domain(domain, snov_token)
            new_results = [v for v in results if v["email"] not in existing]
            all_new.extend(new_results)
            existing.update(v["email"] for v in new_results)
            if new_results:
                print(f"  {domain}: {len(new_results)} new contacts")
            time.sleep(1)
        print()

    # Save results
    vendors.extend(all_new)
    save_vendors(vendors)

    print(f"\n📊 Results:")
    print(f"  New recruiters found: {len(all_new)}")
    print(f"  Total vendor list: {len(vendors)}")
    
    if all_new:
        print(f"\n  New contacts:")
        for v in all_new[:10]:
            print(f"    {v['name'] or 'Unknown'} @ {v['company']} — {v['email']} ({v['source']})")


if __name__ == "__main__":
    main()
