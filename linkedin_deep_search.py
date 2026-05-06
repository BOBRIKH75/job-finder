#!/usr/bin/env python3
"""LinkedIn Deep Search + Recruiter Finder + Auto-Apply Pipeline.

Strategy:
1. Deep LinkedIn search with 12+ queries (public API, no login)
2. Find ALL recruiter/HR emails via Hunter.io + Google + job description
3. Auto-send CV to every found recruiter
4. Export jobs to found_jobs.json so AI Agent auto-applies via Playwright
5. Generate "not applied" report with direct links for manual apply

Runs as part of daily-jobs.yml after find_jobs.py.
"""
import os, re, json, urllib.request, ssl, hashlib
from pathlib import Path
from datetime import datetime

HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "")
CONTACTED_FILE = Path(__file__).parent / "contacted.json"
FOUND_JOBS_FILE = Path(__file__).parent / "found_jobs.json"
REPORT_FILE = Path(__file__).parent / "apply_report.json"

# ══════════════════════════════════════════════════════════════
# DEEP SEARCH — 12 queries covering all angles
# ══════════════════════════════════════════════════════════════

DEEP_QUERIES = [
    "Java Spring Boot C2C contract remote",
    "Java backend developer contract remote",
    "Java Kafka Kubernetes microservices contract",
    "Senior Java developer remote contract",
    "Java Spring Cloud AWS contract",
    "Java microservices Docker Kubernetes contract",
    "Java developer corp-to-corp remote",
    "Senior Software Engineer Java contract",
    "Java GraphQL MongoDB contract",
    "Java REST API developer contract remote",
    "Java Spring Boot developer Denver Colorado",
    "Java backend engineer contract 2026",
]


def search_linkedin_jobs(query: str, limit: int = 25) -> list[dict]:
    """Search LinkedIn jobs via jobspy (no login, public listings)."""
    try:
        from jobspy import scrape_jobs
        jobs = scrape_jobs(
            site_name=["linkedin"],
            search_term=query,
            location="USA",
            results_wanted=limit,
            hours_old=168,
            country_indeed="USA",
        )
        results = []
        for _, row in jobs.iterrows():
            results.append({
                "title": str(row.get("title", "")),
                "company": str(row.get("company", "")),
                "location": str(row.get("location", "")),
                "url": str(row.get("job_url", "")),
                "description": str(row.get("description", ""))[:3000],
                "posted": str(row.get("date_posted", "")),
                "source": "linkedin",
            })
        return results
    except Exception as e:
        print(f"  ⚠️ Search error: {e}")
        return []


# ══════════════════════════════════════════════════════════════
# RECRUITER FINDING — multiple methods, find as many as possible
# ══════════════════════════════════════════════════════════════

def extract_emails_from_text(text: str) -> list[str]:
    """Pull real email addresses from any text."""
    if not text:
        return []
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    skip = ['noreply', 'no-reply', 'donotreply', 'support@', 'info@indeed',
            'privacy@', 'abuse@', 'postmaster@', 'mailer-daemon', 'jobs@indeed',
            'careers@indeed', 'apply@', 'notifications@', 'alert@', 'feedback@']
    return list(set(e.lower() for e in emails if not any(s in e.lower() for s in skip)))


def find_recruiter_hunter(company: str) -> list[dict]:
    """Find ALL recruiter/HR emails via Hunter.io (returns multiple)."""
    if not HUNTER_API_KEY:
        return []
    try:
        domain = _guess_domain(company)
        if not domain:
            return []
        url = f"https://api.hunter.io/v2/domain-search?domain={domain}&type=personal&limit=10&api_key={HUNTER_API_KEY}"
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            data = json.loads(r.read())
        emails = data.get("data", {}).get("emails", [])
        results = []
        # Prioritize HR/recruiting roles, but include all
        hr_keywords = ["recruit", "talent", "hr", "people", "hiring", "human resource", "staffing"]
        for e in emails:
            dept = (e.get("department") or "").lower()
            position = (e.get("position") or "").lower()
            is_hr = any(k in dept + position for k in hr_keywords)
            results.append({
                "email": e["value"],
                "name": f"{e.get('first_name', '')} {e.get('last_name', '')}".strip(),
                "position": e.get("position", ""),
                "source": "hunter.io",
                "is_hr": is_hr,
                "confidence": e.get("confidence", 0),
            })
        # Sort: HR first, then by confidence
        results.sort(key=lambda x: (not x["is_hr"], -x["confidence"]))
        return results
    except Exception:
        return []


def find_recruiter_google(company: str) -> list[dict]:
    """Google search for recruiter emails at company."""
    try:
        query = f'"{company}" recruiter OR HR OR "talent acquisition" email'
        url = f"https://www.google.com/search?q={urllib.request.quote(query)}&num=10"
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            html = r.read().decode("utf-8", errors="ignore")
        emails = extract_emails_from_text(html)
        skip_domains = ["google.", "example.", "schema.", "w3.org", "mozilla.", "apple."]
        real = [e for e in emails if not any(d in e for d in skip_domains)]
        return [{"email": e, "name": "", "position": "recruiter", "source": "google"} for e in real[:3]]
    except Exception:
        return []


def find_all_recruiters(company: str, description: str = "") -> list[dict]:
    """Find ALL possible recruiter/HR contacts for a company."""
    all_contacts = []
    seen_emails = set()

    # 1. Emails embedded in job description
    desc_emails = extract_emails_from_text(description)
    for e in desc_emails:
        if e not in seen_emails:
            seen_emails.add(e)
            all_contacts.append({"email": e, "name": "", "position": "from posting", "source": "description"})

    # 2. Hunter.io (most reliable, returns multiple)
    hunter_results = find_recruiter_hunter(company)
    for r in hunter_results:
        if r["email"] not in seen_emails:
            seen_emails.add(r["email"])
            all_contacts.append(r)

    # 3. Google fallback
    if len(all_contacts) < 2:
        google_results = find_recruiter_google(company)
        for r in google_results:
            if r["email"] not in seen_emails:
                seen_emails.add(r["email"])
                all_contacts.append(r)

    return all_contacts


def _guess_domain(company: str) -> str:
    """Guess company domain from name."""
    clean = re.sub(r'[^a-z0-9]', '', company.lower())
    if not clean:
        return ""
    guesses = [f"{clean}.com", f"{clean}.io", f"{clean}.co"]
    for g in guesses:
        try:
            req = urllib.request.Request(f"https://{g}", headers={"User-Agent": "Mozilla/5.0"})
            urllib.request.urlopen(req, timeout=3)
            return g
        except Exception:
            continue
    return f"{clean}.com"


# ══════════════════════════════════════════════════════════════
# OUTREACH — send CV to ALL found contacts
# ══════════════════════════════════════════════════════════════

def email_hash(email: str) -> str:
    return hashlib.md5(email.lower().encode()).hexdigest()[:12]


def load_contacted() -> dict:
    if CONTACTED_FILE.exists():
        with open(CONTACTED_FILE) as f:
            return json.load(f)
    return {}


def save_contacted(data: dict):
    with open(CONTACTED_FILE, "w") as f:
        json.dump(data, f, indent=2)


def send_to_all_recruiters(results: list[dict]) -> int:
    """Send CV to ALL found recruiters."""
    from outreach import send_outreach, build_outreach_email

    if not os.environ.get("GMAIL_APP_PASSWORD"):
        print("  ⚠️ No GMAIL_APP_PASSWORD — skipping emails")
        return 0

    contacted = load_contacted()
    sent = 0

    for r in results:
        for contact in r.get("contacts", []):
            email = contact["email"]
            eh = email_hash(email)
            if eh in contacted:
                continue

            subject, html = build_outreach_email(
                contact.get("name", ""),
                r["title"],
                r["company"]
            )
            print(f"  📧 → {email} ({r['company']} | {contact.get('position', '?')})")

            if send_outreach(email, subject, html):
                contacted[eh] = {
                    "email": email,
                    "date": datetime.now().isoformat(),
                    "job": r["title"],
                    "company": r["company"],
                    "url": r.get("url", ""),
                    "recruiter": contact.get("name", ""),
                    "source": contact.get("source", ""),
                }
                sent += 1

    save_contacted(contacted)
    return sent


# ══════════════════════════════════════════════════════════════
# EXPORT — feed jobs to AI Agent for auto-apply
# ══════════════════════════════════════════════════════════════

def export_for_agent(results: list[dict]) -> int:
    """Append LinkedIn deep search jobs to found_jobs.json for AI Agent to apply."""
    existing = {"jobs": [], "count": 0}
    if FOUND_JOBS_FILE.exists():
        try:
            with open(FOUND_JOBS_FILE) as f:
                existing = json.load(f)
        except Exception:
            pass

    existing_urls = {j.get("url", "") for j in existing.get("jobs", [])}
    added = 0

    for r in results:
        if r["url"] and r["url"] not in existing_urls:
            existing["jobs"].append({
                "title": r["title"],
                "company": r["company"],
                "url": r["url"],
                "location": r.get("location", ""),
                "description": r.get("description", "")[:2000],
                "score": r.get("score", 50),
                "is_c2c": r.get("is_c2c", False),
                "source": "linkedin_deep",
                "found_at": datetime.now().isoformat(),
            })
            existing_urls.add(r["url"])
            added += 1

    existing["count"] = len(existing["jobs"])
    existing["exported_at"] = datetime.now().isoformat()
    with open(FOUND_JOBS_FILE, "w") as f:
        json.dump(existing, f, indent=2)

    return added


# ══════════════════════════════════════════════════════════════
# REPORT — jobs that need manual apply
# ══════════════════════════════════════════════════════════════

def generate_apply_report(results: list[dict]) -> dict:
    """Generate report of jobs: applied (emailed recruiter) vs not applied (need manual)."""
    applied = []
    not_applied = []

    for r in results:
        if r.get("emails_sent", 0) > 0:
            applied.append({
                "title": r["title"],
                "company": r["company"],
                "url": r["url"],
                "contacts_emailed": r.get("emails_sent", 0),
            })
        else:
            not_applied.append({
                "title": r["title"],
                "company": r["company"],
                "url": r["url"],
                "location": r.get("location", ""),
                "reason": "No recruiter email found — apply manually via link",
            })

    report = {
        "date": datetime.now().isoformat(),
        "applied_via_email": applied,
        "not_applied_need_manual": not_applied,
        "summary": {
            "total_jobs": len(results),
            "emailed_recruiters": len(applied),
            "need_manual_apply": len(not_applied),
        }
    }
    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2)
    return report


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print(f"🔍 LinkedIn Deep Search v2 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Queries: {len(DEEP_QUERIES)}")
    print(f"  Hunter.io: {'✅' if HUNTER_API_KEY else '❌'}")
    print(f"  Gmail: {'✅' if os.environ.get('GMAIL_APP_PASSWORD') else '❌'}")
    print()

    # Phase 1: Deep search
    all_jobs = []
    seen_urls = set()
    for q in DEEP_QUERIES:
        jobs = search_linkedin_jobs(q, limit=25)
        new = [j for j in jobs if j["url"] not in seen_urls]
        for j in new:
            seen_urls.add(j["url"])
        all_jobs.extend(new)
        if jobs:
            print(f"  ✅ '{q[:45]}' → {len(jobs)} ({len(new)} new)")

    # Deduplicate by company+title
    dedup = {}
    for j in all_jobs:
        key = f"{j['company'].lower()}|{j['title'].lower()}"
        if key not in dedup:
            dedup[key] = j
    all_jobs = list(dedup.values())
    print(f"\n📊 {len(all_jobs)} unique jobs found")

    # Phase 2: Find recruiters for each job
    print("\n🔎 Finding recruiters/HR contacts...")
    results = []
    contacted = load_contacted()
    contacted_emails = set(v.get("email", "") for v in contacted.values())

    for job in all_jobs:
        company = job["company"]
        if not company or len(company) < 3:
            continue

        contacts = find_all_recruiters(company, job.get("description", ""))
        # Filter already contacted
        new_contacts = [c for c in contacts if c["email"] not in contacted_emails]

        is_c2c = any(k in job.get("description", "").lower()
                     for k in ["c2c", "corp-to-corp", "corp to corp", "1099", "w2/c2c"])

        results.append({
            "title": job["title"],
            "company": company,
            "url": job["url"],
            "location": job.get("location", ""),
            "description": job.get("description", ""),
            "contacts": new_contacts,
            "is_c2c": is_c2c,
            "score": 60 if is_c2c else 40,
        })

        if new_contacts:
            print(f"  ✅ {company}: {len(new_contacts)} contacts ({', '.join(c['email'] for c in new_contacts[:2])})")

    jobs_with_contacts = [r for r in results if r.get("contacts")]
    jobs_without = [r for r in results if not r.get("contacts")]
    print(f"\n📊 {len(jobs_with_contacts)} jobs with recruiter contacts, {len(jobs_without)} without")

    # Phase 3: Send CV to ALL found recruiters
    print("\n📧 Sending CV to all found recruiters...")
    sent = send_to_all_recruiters(results)
    print(f"✅ {sent} emails sent")

    # Mark how many emails sent per job
    contacted_after = load_contacted()
    for r in results:
        r["emails_sent"] = sum(1 for c in r.get("contacts", [])
                               if email_hash(c["email"]) in contacted_after)

    # Phase 4: Export to found_jobs.json for AI Agent auto-apply
    print("\n📤 Exporting jobs for AI Agent auto-apply...")
    added = export_for_agent(results)
    print(f"  {added} new jobs added to found_jobs.json")

    # Phase 5: Generate apply report
    report = generate_apply_report(results)
    print(f"\n📋 Apply Report:")
    print(f"  ✅ Emailed recruiters: {report['summary']['emailed_recruiters']} jobs")
    print(f"  🔗 Need manual apply: {report['summary']['need_manual_apply']} jobs")

    # Print manual apply links
    if report["not_applied_need_manual"]:
        print("\n🔗 APPLY MANUALLY (no recruiter found):")
        for j in report["not_applied_need_manual"][:20]:
            print(f"  → {j['title']} @ {j['company']}")
            print(f"    {j['url']}")

    print(f"\n🎯 DONE: {len(results)} jobs | {sent} emailed | {added} queued for auto-apply")


if __name__ == "__main__":
    main()
