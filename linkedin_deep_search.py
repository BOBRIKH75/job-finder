#!/usr/bin/env python3
"""LinkedIn Deep Search + Recruiter Finder — safe, no login needed.

Strategy (won't get restricted):
1. LinkedIn job search via jobspy (public API, no login)
2. Extract company name + job poster from listings
3. Find recruiter email via Hunter.io API (you have key)
4. Find recruiter via Apollo.io (free 10K credits/month)
5. Google search fallback: "{company} recruiter email Java"

SAFE approach — never logs into LinkedIn, never applies on LinkedIn.
Only READS public job listings and finds recruiter contact info externally.
"""
import os, re, json, urllib.request, ssl
from pathlib import Path

HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "")
CONTACTED_FILE = Path(__file__).parent / "contacted.json"


def search_linkedin_jobs(query: str = "Java Spring Boot contract remote", limit: int = 30) -> list[dict]:
    """Search LinkedIn jobs via jobspy (no login, public listings)."""
    try:
        from jobspy import scrape_jobs
        jobs = scrape_jobs(
            site_name=["linkedin"],
            search_term=query,
            location="USA",
            results_wanted=limit,
            hours_old=168,  # last 7 days
            country_indeed="USA",
        )
        results = []
        for _, row in jobs.iterrows():
            results.append({
                "title": str(row.get("title", "")),
                "company": str(row.get("company", "")),
                "location": str(row.get("location", "")),
                "url": str(row.get("job_url", "")),
                "description": str(row.get("description", ""))[:2000],
                "posted": str(row.get("date_posted", "")),
            })
        return results
    except Exception as e:
        print(f"  LinkedIn search error: {e}")
        return []


def find_recruiter_hunter(company: str, role: str = "recruiter") -> dict | None:
    """Find recruiter email via Hunter.io API (50 free/month)."""
    if not HUNTER_API_KEY:
        return None
    try:
        # Domain search — find people at company
        domain = _guess_domain(company)
        if not domain:
            return None
        url = f"https://api.hunter.io/v2/domain-search?domain={domain}&type=personal&limit=5&api_key={HUNTER_API_KEY}"
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            data = json.loads(r.read())
        emails = data.get("data", {}).get("emails", [])
        # Find someone in recruiting/HR/talent
        for e in emails:
            dept = (e.get("department") or "").lower()
            position = (e.get("position") or "").lower()
            if any(k in dept + position for k in ["recruit", "talent", "hr", "people", "hiring"]):
                return {"email": e["value"], "name": f"{e.get('first_name','')} {e.get('last_name','')}".strip(),
                        "position": e.get("position", ""), "source": "hunter.io"}
        # Fallback: first email found
        if emails:
            e = emails[0]
            return {"email": e["value"], "name": f"{e.get('first_name','')} {e.get('last_name','')}".strip(),
                    "position": e.get("position", ""), "source": "hunter.io"}
    except Exception:
        pass
    return None


def find_recruiter_apollo(company: str) -> dict | None:
    """Find recruiter via Apollo.io free API (10K credits/month)."""
    # Apollo requires web app or API key — use their free people search
    # This is a simplified version; full integration needs APOLLO_API_KEY
    api_key = os.environ.get("APOLLO_API_KEY", "")
    if not api_key:
        return None
    try:
        import httpx
        resp = httpx.post("https://api.apollo.io/api/v1/mixed_people/search",
            json={
                "api_key": api_key,
                "q_organization_name": company,
                "person_titles": ["recruiter", "talent acquisition", "hiring manager"],
                "per_page": 3,
            }, timeout=10)
        if resp.status_code == 200:
            people = resp.json().get("people", [])
            if people:
                p = people[0]
                return {"email": p.get("email", ""), "name": p.get("name", ""),
                        "position": p.get("title", ""), "source": "apollo.io",
                        "linkedin": p.get("linkedin_url", "")}
    except Exception:
        pass
    return None


def find_recruiter_google(company: str) -> dict | None:
    """Google search for recruiter email (free, no API key)."""
    try:
        query = f'"{company}" recruiter OR "talent acquisition" email Java developer'
        url = f"https://www.google.com/search?q={urllib.request.quote(query)}&num=5"
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            html = r.read().decode("utf-8", errors="ignore")
        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', html)
        # Filter out google/example emails
        real = [e for e in set(emails) if not any(d in e for d in ["google.", "example.", "schema."])]
        if real:
            return {"email": real[0], "name": "", "position": "recruiter", "source": "google"}
    except Exception:
        pass
    return None


def find_recruiter(company: str) -> dict | None:
    """Try all methods to find a recruiter at this company."""
    # 1. Hunter.io (most reliable)
    r = find_recruiter_hunter(company)
    if r and r.get("email"):
        return r
    # 2. Apollo.io
    r = find_recruiter_apollo(company)
    if r and r.get("email"):
        return r
    # 3. Google fallback
    return find_recruiter_google(company)


def _guess_domain(company: str) -> str:
    """Guess company domain from name."""
    clean = re.sub(r'[^a-z0-9]', '', company.lower())
    # Common patterns
    guesses = [f"{clean}.com", f"{clean}.io", f"{clean}.co"]
    for g in guesses:
        try:
            urllib.request.urlopen(f"https://{g}", timeout=3)
            return g
        except Exception:
            continue
    return f"{clean}.com"


def load_contacted() -> set:
    if CONTACTED_FILE.exists():
        return set(json.loads(CONTACTED_FILE.read_text()))
    return set()


def save_contacted(contacted: set):
    CONTACTED_FILE.write_text(json.dumps(sorted(contacted)))


def deep_search_and_find_recruiters(queries: list[str] = None) -> list[dict]:
    """Full pipeline: search LinkedIn → find recruiters → return actionable list."""
    if queries is None:
        queries = [
            "Java Spring Boot C2C contract remote",
            "Java backend developer contract",
            "Java Kafka Kubernetes microservices contract",
            "Senior Java developer remote contract",
        ]

    contacted = load_contacted()
    all_results = []

    print("🔍 LinkedIn Deep Search (public, no login)...")
    for q in queries:
        jobs = search_linkedin_jobs(q, limit=15)
        print(f"  '{q[:40]}' → {len(jobs)} jobs")

        for job in jobs:
            company = job["company"]
            if not company or company in contacted:
                continue

            # Find recruiter
            recruiter = find_recruiter(company)
            if recruiter and recruiter.get("email"):
                all_results.append({
                    "job_title": job["title"],
                    "company": company,
                    "job_url": job["url"],
                    "recruiter_email": recruiter["email"],
                    "recruiter_name": recruiter.get("name", ""),
                    "recruiter_source": recruiter.get("source", ""),
                })

    # Deduplicate by company
    seen = set()
    unique = []
    for r in all_results:
        if r["company"] not in seen:
            seen.add(r["company"])
            unique.append(r)

    print(f"\n📊 Found {len(unique)} recruiters from {len(all_results)} matches")
    return unique


def send_to_all_found_recruiters(results: list[dict]):
    """Send CV outreach email to ALL found recruiters (not just posting-embedded ones)."""
    from outreach import send_outreach, build_outreach_email, load_contacted, save_contacted, email_hash
    from datetime import datetime

    if not os.environ.get("GMAIL_APP_PASSWORD"):
        print("  ⚠️  No GMAIL_APP_PASSWORD — skipping recruiter emails")
        return 0

    contacted = load_contacted()
    sent = 0

    for r in results:
        email = r["recruiter_email"]
        eh = email_hash(email)
        if eh in contacted:
            print(f"  ⏭️  Already contacted: {email}")
            continue

        subject, html = build_outreach_email(
            r.get("recruiter_name", ""),
            r["job_title"],
            r["company"]
        )
        print(f"  📧 Sending to {email} ({r['company']})...")

        if send_outreach(email, subject, html):
            contacted[eh] = {
                "email": email,
                "date": datetime.now().isoformat(),
                "job": r["job_title"],
                "company": r["company"],
                "url": r.get("job_url", ""),
                "recruiter": r.get("recruiter_name", ""),
                "source": r.get("recruiter_source", ""),
            }
            sent += 1
            print(f"  ✅ Sent! ({sent} total)")

    save_contacted(contacted)
    print(f"\n📧 Deep Search Outreach: {sent} emails sent to new recruiters")
    return sent


if __name__ == "__main__":
    results = deep_search_and_find_recruiters()
    for r in results[:15]:
        print(f"  {r['company']:20s} | {r['recruiter_email']:30s} | {r['recruiter_source']}")

    # Auto-send CV to ALL found recruiters
    sent = send_to_all_found_recruiters(results)
    print(f"\n🎯 Total: {len(results)} found, {sent} emailed")
