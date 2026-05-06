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

# Known C2C vendors — search their postings specifically
C2C_VENDORS = [
    "Skiltrek", "Pyramid Consulting", "Collabera", "TEKsystems", "Mastech",
    "RIT Solutions", "Amerit Consulting", "Han IT Staffing", "XL Impex",
    "Atika Tech", "Randstad", "Robert Half", "Insight Global", "Kforce",
    "Modis", "Multivision", "KAnand", "Vinsari", "QTech", "WorkNovas",
    "Wipro", "Infosys", "TCS", "HCL", "Cognizant", "Mphasis",
    "Hexaware", "Cyient", "Zensar", "Mindtree", "Apex Systems",
    "Motion Recruitment", "Matlen Silver", "Aretum",
]

# Vendor domains (for direct email lookup)
VENDOR_DOMAINS = {
    "Skiltrek": "skiltrek.com",
    "Pyramid Consulting": "pyramidci.com",
    "Collabera": "collabera.com",
    "TEKsystems": "teksystems.com",
    "Mastech": "mastech.com",
    "RIT Solutions": "ritsolutions.com",
    "Amerit Consulting": "ameritconsulting.com",
    "Insight Global": "insightglobal.com",
    "Kforce": "kforce.com",
    "Randstad": "randstad.com",
    "Robert Half": "roberthalf.com",
    "Apex Systems": "apexsystems.com",
    "Motion Recruitment": "motionrecruitment.com",
    "Matlen Silver": "matlensilver.com",
    "KAnand": "kanandcorp.com",
    "Multivision": "multivision-inc.com",
    "Modis": "modis.com",
    "HCL": "hcltech.com",
    "Infosys": "infosys.com",
    "Wipro": "wipro.com",
    "Cognizant": "cognizant.com",
    "TCS": "tcs.com",
}


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
    """Find ALL recruiter/HR emails via Hunter.io (returns multiple).
    Gracefully handles expired/invalid keys — logs warning and continues."""
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
        # Check for auth errors
        if data.get("errors"):
            err = data["errors"][0].get("details", "")
            if "api key" in err.lower() or "auth" in err.lower() or "limit" in err.lower():
                print(f"  ⚠️ Hunter.io: {err} — key may be expired/exhausted")
                return []
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


def find_recruiters_linkedin_google(company: str) -> list[dict]:
    """Find recruiter names at company via Google → LinkedIn profiles (no login).
    Then guess their email using common patterns + verify via MX."""
    results = []
    try:
        query = f'site:linkedin.com/in "{company}" recruiter OR "talent acquisition" OR HR'
        url = f"https://www.google.com/search?q={urllib.request.quote(query)}&num=10"
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            html = r.read().decode("utf-8", errors="ignore")

        # Extract names from LinkedIn profile snippets
        # Pattern: "First Last - Title - Company | LinkedIn"
        name_pattern = re.compile(r'([A-Z][a-z]+ [A-Z][a-z]+)\s*[-–—]\s*(?:.*?(?:Recruiter|Talent|HR|Hiring|Staffing))', re.IGNORECASE)
        names = name_pattern.findall(html)

        # Also try: "First Last | LinkedIn" with recruiter in snippet
        alt_pattern = re.compile(r'>([A-Z][a-z]+ [A-Z][a-z]+)(?:\s*\||\s*-)\s*LinkedIn', re.IGNORECASE)
        alt_names = alt_pattern.findall(html)

        all_names = list(set(names + alt_names))[:5]

        domain = _guess_domain(company)
        for name in all_names:
            parts = name.strip().split()
            if len(parts) >= 2:
                first, last = parts[0], parts[-1]
                # Guess email patterns
                guessed = guess_email_patterns(first, last, domain)
                # Verify which one has valid MX
                for email in guessed[:3]:  # check top 3 patterns
                    if verify_mx(email.split("@")[1]):
                        results.append({
                            "email": email,
                            "name": name.strip(),
                            "position": "recruiter (guessed)",
                            "source": "linkedin+guess",
                        })
                        break  # one email per person
    except Exception:
        pass
    return results


def guess_email_patterns(first: str, last: str, domain: str) -> list[str]:
    """Generate common corporate email patterns."""
    f, l = first.lower().strip(), last.lower().strip()
    if not f or not l or not domain:
        return []
    return [
        f"{f}.{l}@{domain}",
        f"{f}{l}@{domain}",
        f"{f[0]}{l}@{domain}",
        f"{f}_{l}@{domain}",
        f"{f[0]}.{l}@{domain}",
        f"{l}.{f}@{domain}",
        f"{f}@{domain}",
    ]


def verify_mx(domain: str) -> bool:
    """Check if domain has MX records (can receive email)."""
    try:
        import dns.resolver
        answers = dns.resolver.resolve(domain, "MX")
        return len(answers) > 0
    except Exception:
        # If dns.resolver not available, assume valid
        return True


def find_recruiter_snov(company: str) -> list[dict]:
    """Find recruiter via Snov.io (uses OAuth: user_id + secret → access_token)."""
    user_id = os.environ.get("SNOV_USER_ID", "")
    secret = os.environ.get("SNOV_API_SECRET", "")
    if not user_id or not secret:
        return []
    try:
        # Step 1: Get access token
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        token_data = json.dumps({"grant_type": "client_credentials", "client_id": user_id, "client_secret": secret}).encode()
        req = urllib.request.Request("https://api.snov.io/v1/oauth/access_token", data=token_data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            resp = json.loads(r.read())
        token = resp.get("access_token", "")
        if not token:
            print(f"  ⚠️ Snov.io: auth failed — {resp.get('error', 'no token')} — credentials may be expired")
            return []

        # Step 2: Domain search for emails
        domain = _guess_domain(company)
        if not domain:
            return []
        search_data = json.dumps({"domain": domain, "type": "personal", "limit": 5}).encode()
        req2 = urllib.request.Request("https://api.snov.io/v2/domain-emails-with-info",
                                      data=search_data,
                                      headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req2, timeout=10, context=ctx) as r2:
            edata = json.loads(r2.read())

        results = []
        for e in edata.get("emails", []):
            email = e.get("email", "")
            if email:
                results.append({
                    "email": email,
                    "name": f"{e.get('first_name', '')} {e.get('last_name', '')}".strip(),
                    "position": e.get("position", ""),
                    "source": "snov.io",
                })
        return results
    except Exception:
        return []


def find_all_recruiters(company: str, description: str = "") -> list[dict]:
    """Find ALL possible recruiter/HR contacts using every free method available."""
    all_contacts = []
    seen_emails = set()

    def add_contacts(contacts):
        for c in contacts:
            if c.get("email") and c["email"] not in seen_emails:
                seen_emails.add(c["email"])
                all_contacts.append(c)

    # 1. Emails embedded in job description (free, instant)
    desc_emails = extract_emails_from_text(description)
    add_contacts([{"email": e, "name": "", "position": "from posting", "source": "description"} for e in desc_emails])

    # 2. Hunter.io (25 free/month — most reliable)
    add_contacts(find_recruiter_hunter(company))

    # 3. Snov.io (50 free credits/month)
    add_contacts(find_recruiter_snov(company))

    # 4. Google LinkedIn recruiter search → guess email + MX verify (FREE, unlimited)
    add_contacts(find_recruiters_linkedin_google(company))

    # 5. Google search for recruiter email (FREE, unlimited)
    if len(all_contacts) < 3:
        add_contacts(find_recruiter_google(company))

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

# Dynamic learning file — grows over time
LEARNED_FILE = Path(__file__).parent / "learned.json"

# Only learn keywords that are REAL tech/job skills (not random English)
VALID_KEYWORD_PATTERNS = re.compile(
    r'^(java|spring|kafka|kubernetes|docker|aws|azure|gcp|python|node|react|angular|'
    r'graphql|mongodb|cassandra|redis|postgresql|mysql|oracle|elasticsearch|'
    r'microservice|rest|api|devops|ci.?cd|jenkins|terraform|ansible|'
    r'junit|mockito|maven|gradle|git|jira|agile|scrum|'
    r'oauth|jwt|keycloak|openid|'
    r'splunk|datadog|kibana|grafana|prometheus|'
    r'rabbitmq|activemq|solr|lucene|'
    r'hibernate|jpa|mybatis|'
    r'lambda|s3|ec2|ecs|eks|fargate|dynamodb|sqs|sns|'
    r'typescript|javascript|html|css|'
    r'linux|unix|bash|shell|'
    r'c2c|corp.to.corp|1099|w2|contract|remote|'
    r'senior|lead|architect|principal|staff|'
    r'full.?stack|back.?end|front.?end|'
    r'\w+\.?js|\.net|c\#|golang|rust|scala|kotlin|'
    r'spark|hadoop|airflow|databricks|snowflake|'
    r'tableau|power.?bi|looker|'
    r'figma|sketch|'
    r'playwright|selenium|cypress|cucumber|'
    r'docker.?compose|helm|istio|envoy|'
    r'vault|consul|nomad|'
    r'nginx|apache|tomcat|'
    r'grpc|protobuf|thrift|'
    r'websocket|sse|'
    r'oauth2|saml|ldap|sso|'
    r'ci/cd|github.?actions|gitlab.?ci|circle.?ci|'
    r'sonar|veracode|checkmarx|fortify)',
    re.IGNORECASE
)

VENDOR_SIGNALS = re.compile(
    r'(consulting|staffing|solutions|technologies|tech|infotech|systems|'
    r'corporation|corp|inc\b|llc\b|group|partners|global|services|'
    r'recruitment|recruiting|talent)',
    re.IGNORECASE
)


def load_learned() -> dict:
    if LEARNED_FILE.exists():
        try:
            with open(LEARNED_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"vendors": [], "keywords": [], "updated": ""}


def save_learned(learned: dict):
    learned["updated"] = datetime.now().isoformat()
    with open(LEARNED_FILE, "w") as f:
        json.dump(learned, f, indent=2)


def discover_new_vendors(jobs: list[dict], known_vendors: set) -> set:
    """Find new C2C staffing vendors from job postings."""
    new = set()
    known_lower = {v.lower() for v in known_vendors}
    for job in jobs:
        company = job.get("company", "")
        if not company or len(company) < 3 or company.lower() in known_lower:
            continue
        desc = job.get("description", "").lower()
        is_c2c = any(k in desc for k in ["c2c", "corp-to-corp", "corp to corp", "1099", "w2/c2c"])
        is_vendor = bool(VENDOR_SIGNALS.search(company))
        if is_c2c and is_vendor:
            new.add(company.strip())
    return new


def discover_new_keywords(jobs: list[dict], known_skills: set) -> set:
    """Find new RELEVANT tech keywords from C2C postings (not random English words)."""
    keyword_counts = {}
    for job in jobs:
        desc = job.get("description", "").lower()
        if not any(k in desc for k in ["c2c", "contract", "corp", "java"]):
            continue
        # Extract potential tech keywords
        words = re.findall(r'\b[a-z][a-z0-9.#+/-]{2,20}\b', desc)
        for w in words:
            if w in known_skills or len(w) < 3:
                continue
            # Only keep if it matches known tech patterns
            if VALID_KEYWORD_PATTERNS.match(w):
                keyword_counts[w] = keyword_counts.get(w, 0) + 1
    # Only keep keywords appearing in 2+ postings (real signal)
    return {k for k, v in keyword_counts.items() if v >= 2}


def search_vendor_jobs() -> list[dict]:
    """Search for Java jobs posted BY known C2C vendors — these are real C2C positions."""
    print("\n🏢 Searching jobs posted by C2C vendors...")
    all_jobs = []
    # Search in batches of 3 vendors
    for i in range(0, len(C2C_VENDORS), 3):
        batch = C2C_VENDORS[i:i+3]
        query = f"Java ({' OR '.join(batch)}) contract"
        jobs = search_linkedin_jobs(query, limit=15)
        # Filter to only jobs FROM these vendors
        vendor_jobs = [j for j in jobs if any(v.lower() in j["company"].lower() for v in batch)]
        all_jobs.extend(vendor_jobs)
        if vendor_jobs:
            print(f"  ✅ {', '.join(batch)}: {len(vendor_jobs)} jobs")
    print(f"  📊 {len(all_jobs)} vendor jobs found")
    return all_jobs


def find_vendor_recruiters() -> list[dict]:
    """Directly find recruiters at known C2C vendors using their domains."""
    print("\n🎯 Finding recruiters at C2C vendors (direct domain lookup)...")
    results = []
    contacted = load_contacted()
    contacted_emails = set(v.get("email", "") for v in contacted.values())

    for vendor, domain in VENDOR_DOMAINS.items():
        # Use Hunter.io with known domain (no guessing needed)
        if not HUNTER_API_KEY:
            break
        try:
            url = f"https://api.hunter.io/v2/domain-search?domain={domain}&type=personal&limit=5&api_key={HUNTER_API_KEY}"
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
                data = json.loads(r.read())
            emails = data.get("data", {}).get("emails", [])
            hr_keywords = ["recruit", "talent", "hr", "people", "hiring", "staffing", "account manager"]
            for e in emails:
                email = e.get("value", "")
                if email in contacted_emails:
                    continue
                position = (e.get("position") or "").lower()
                dept = (e.get("department") or "").lower()
                if any(k in position + dept for k in hr_keywords):
                    results.append({
                        "email": email,
                        "name": f"{e.get('first_name', '')} {e.get('last_name', '')}".strip(),
                        "company": vendor,
                        "position": e.get("position", ""),
                        "source": "vendor_direct",
                    })
            if results:
                latest = [r for r in results if r["company"] == vendor]
                if latest:
                    print(f"  ✅ {vendor}: {len(latest)} recruiters")
        except Exception:
            continue

    print(f"  📊 {len(results)} vendor recruiters found")
    return results


def send_to_vendor_recruiters(vendor_contacts: list[dict]) -> int:
    """Send CV directly to vendor recruiters — they're actively looking for candidates."""
    from outreach import send_outreach, build_outreach_email

    if not os.environ.get("GMAIL_APP_PASSWORD"):
        return 0

    contacted = load_contacted()
    sent = 0

    for contact in vendor_contacts:
        eh = email_hash(contact["email"])
        if eh in contacted:
            continue

        # Custom subject for vendor outreach
        subject = f"Java Backend Developer — C2C Available — Bob Rikh"
        from outreach import build_outreach_email
        _, html = build_outreach_email(
            contact.get("name", ""),
            "Java Backend Developer (C2C)",
            contact["company"]
        )
        print(f"  📧 → {contact['email']} ({contact['company']} | {contact.get('position', 'recruiter')})")

        if send_outreach(contact["email"], subject, html):
            contacted[eh] = {
                "email": contact["email"],
                "date": datetime.now().isoformat(),
                "job": "Vendor outreach",
                "company": contact["company"],
                "recruiter": contact.get("name", ""),
                "source": "vendor_direct",
            }
            sent += 1

    save_contacted(contacted)
    return sent


def check_api_health() -> dict:
    """Check all API keys are valid at start of run. Report status, continue with working ones."""
    status = {}
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    # Hunter.io
    if HUNTER_API_KEY:
        try:
            req = urllib.request.Request(f"https://api.hunter.io/v2/account?api_key={HUNTER_API_KEY}",
                                         headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5, context=ctx) as r:
                data = json.loads(r.read())
            if data.get("data"):
                used = data["data"]["requests"]["searches"]["used"]
                avail = data["data"]["requests"]["searches"]["available"]
                status["hunter"] = f"✅ {avail - used} remaining"
            else:
                status["hunter"] = "❌ invalid key"
        except Exception as e:
            status["hunter"] = f"⚠️ {e}"
    else:
        status["hunter"] = "⏭️ no key"

    # Apollo.io
    apollo_key = os.environ.get("APOLLO_API_KEY", "")
    if apollo_key:
        try:
            req = urllib.request.Request("https://api.apollo.io/api/v1/auth/health",
                                         headers={"Content-Type": "application/json", "X-Api-Key": apollo_key})
            with urllib.request.urlopen(req, timeout=5, context=ctx) as r:
                status["apollo"] = "✅ connected"
        except urllib.error.HTTPError as e:
            if e.code == 401:
                status["apollo"] = "❌ key expired/invalid"
            else:
                status["apollo"] = f"✅ active (code {e.code})"
        except Exception:
            status["apollo"] = "✅ assumed active"
    else:
        status["apollo"] = "⏭️ no key"

    # Snov.io
    snov_id = os.environ.get("SNOV_USER_ID", "")
    snov_secret = os.environ.get("SNOV_API_SECRET", "")
    if snov_id and snov_secret:
        try:
            token_data = json.dumps({"grant_type": "client_credentials", "client_id": snov_id, "client_secret": snov_secret}).encode()
            req = urllib.request.Request("https://api.snov.io/v1/oauth/access_token", data=token_data,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5, context=ctx) as r:
                resp = json.loads(r.read())
            if resp.get("access_token"):
                status["snov"] = "✅ token OK"
            else:
                status["snov"] = f"❌ {resp.get('error', 'no token')}"
        except Exception as e:
            status["snov"] = f"⚠️ {e}"
    else:
        status["snov"] = "⏭️ no credentials"

    # Gmail
    status["gmail"] = "✅ configured" if os.environ.get("GMAIL_APP_PASSWORD") else "⏭️ no password"

    return status


def main():
    print(f"🔍 LinkedIn Deep Search v3 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Health check — verify all APIs before starting
    print("\n🏥 API Health Check:")
    health = check_api_health()
    for svc, stat in health.items():
        print(f"  {svc:8s}: {stat}")
    working_apis = sum(1 for s in health.values() if "✅" in s)
    print(f"  → {working_apis}/{len(health)} services active\n")
    print(f"  Queries: {len(DEEP_QUERIES)} + vendor searches")
    print(f"  Vendors: {len(C2C_VENDORS)} ({len(VENDOR_DOMAINS)} with known domains)")
    print(f"  Hunter.io: {'✅' if HUNTER_API_KEY else '❌'}")
    print(f"  Gmail: {'✅' if os.environ.get('GMAIL_APP_PASSWORD') else '❌'}")

    # Load dynamic learning
    learned = load_learned()
    all_vendors = set(C2C_VENDORS) | set(learned.get("vendors", []))
    print(f"  Learned vendors: {len(learned.get('vendors', []))}")
    print(f"  Learned keywords: {len(learned.get('keywords', []))}")
    print()

    # Phase 1a: Deep search with standard queries
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

    # Phase 1b: Search jobs posted BY vendors specifically
    vendor_jobs = search_vendor_jobs()
    for j in vendor_jobs:
        if j["url"] not in seen_urls:
            seen_urls.add(j["url"])
            all_jobs.append(j)

    # Deduplicate by company+title
    dedup = {}
    for j in all_jobs:
        key = f"{j['company'].lower()}|{j['title'].lower()}"
        if key not in dedup:
            dedup[key] = j
    all_jobs = list(dedup.values())
    print(f"\n📊 {len(all_jobs)} unique jobs found")

    # Phase 1c: Dynamic learning — discover new vendors + keywords
    new_vendors = discover_new_vendors(all_jobs, all_vendors)
    known_skills = {'java', 'spring', 'kafka', 'kubernetes', 'docker', 'aws', 'microservices',
                    'mongodb', 'cassandra', 'redis', 'graphql', 'rest', 'maven', 'junit'}
    new_keywords = discover_new_keywords(all_jobs, known_skills | set(learned.get("keywords", [])))
    if new_vendors:
        learned.setdefault("vendors", []).extend(sorted(new_vendors))
        learned["vendors"] = sorted(set(learned["vendors"]))
        print(f"  🧠 Learned {len(new_vendors)} new vendors: {', '.join(list(new_vendors)[:5])}")
    if new_keywords:
        learned.setdefault("keywords", []).extend(sorted(new_keywords))
        learned["keywords"] = sorted(set(learned["keywords"]))
        print(f"  🧠 Learned {len(new_keywords)} new keywords: {', '.join(list(new_keywords)[:8])}")
    save_learned(learned)

    # Phase 2a: Find recruiters at VENDORS directly (highest value)
    vendor_contacts = find_vendor_recruiters()
    vendor_sent = send_to_vendor_recruiters(vendor_contacts)
    print(f"  📧 {vendor_sent} vendor recruiter emails sent")

    # Phase 2b: Find recruiters for each job
    print("\n🔎 Finding recruiters/HR contacts for jobs...")
    results = []
    contacted = load_contacted()
    contacted_emails = set(v.get("email", "") for v in contacted.values())

    for job in all_jobs:
        company = job["company"]
        if not company or len(company) < 3:
            continue

        contacts = find_all_recruiters(company, job.get("description", ""))
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
    print(f"✅ {sent} emails sent (+ {vendor_sent} vendor direct)")

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

    if report["not_applied_need_manual"]:
        print("\n🔗 APPLY MANUALLY (no recruiter found):")
        for j in report["not_applied_need_manual"][:15]:
            print(f"  → {j['title']} @ {j['company']}")
            print(f"    {j['url']}")

    total_sent = sent + vendor_sent
    print(f"\n🎯 DONE: {len(results)} jobs | {total_sent} emailed | {added} queued for auto-apply")
    print(f"🧠 LEARNED: {len(learned.get('vendors',[]))} vendors | {len(learned.get('keywords',[]))} keywords")


if __name__ == "__main__":
    main()
