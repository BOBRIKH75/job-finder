"""Company portal scanner — checks career pages via free APIs, grows company list daily.

Flow:
1. Load company list (seed + learned)
2. For each company, check Lever API and Greenhouse API
3. Filter jobs matching Java/Spring Boot/Kafka skills
4. When agent applies anywhere, extract company → add to list
5. List grows every day automatically

No browser needed — pure API calls, no CAPTCHA.
"""
import json, re, time
from pathlib import Path
import httpx

COMPANIES_FILE = Path(__file__).parent.parent / "data" / "companies.json"

SKILLS_FILTER = [
    "java", "spring", "kafka", "kubernetes", "microservice", "backend", "back-end",
    "back end", "docker", "aws", "rest api", "graphql", "mongodb", "cassandra",
    "postgresql", "redis", "devops", "ci/cd", "software engineer", "developer",
    "full stack", "fullstack", "platform engineer", "site reliability",
]

# Seed companies known to hire Java developers on Lever/Greenhouse
SEED_LEVER = [
    "netflix", "twitch", "coinbase", "stripe", "figma", "notion", "databricks",
    "cloudflare", "datadog", "elastic", "confluent", "mongodb", "cockroachlabs",
    "hashicorp", "grafana", "temporal", "pulumi", "airbyte", "dbt-labs",
    "snyk", "sonatype", "jfrog", "launchdarkly", "split", "optimizely",
    "pagerduty", "opsgenie", "victorops", "miro", "loom", "calendly",
    "gusto", "rippling", "deel", "remote", "oysterhr", "lattice",
    "lever", "greenhouse", "ashbyhq", "workday",
]

SEED_GREENHOUSE = [
    "axon", "blend", "brex", "chime", "plaid", "marqeta", "affirm",
    "squarespace", "webflow", "vercel", "supabase", "planetscale",
    "cockroachlabs", "timescale", "singlestore", "clickhouse",
    "datadog", "newrelic", "dynatrace", "splunk",
    "twilio", "sendgrid", "messagebird", "vonage",
    "okta", "auth0", "onelogin", "jumpcloud",
    "snowflake", "fivetran", "dbt", "census", "hightouch",
    "thoughtworks", "slalom", "capgemini",
]


def load_companies() -> dict:
    if COMPANIES_FILE.exists():
        try:
            return json.loads(COMPANIES_FILE.read_text())
        except Exception:
            pass
    return {"lever": list(SEED_LEVER), "greenhouse": list(SEED_GREENHOUSE), "discovered": []}


def save_companies(data: dict):
    COMPANIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Deduplicate
    data["lever"] = sorted(set(data.get("lever", [])))
    data["greenhouse"] = sorted(set(data.get("greenhouse", [])))
    data["discovered"] = sorted(set(data.get("discovered", [])))
    COMPANIES_FILE.write_text(json.dumps(data, indent=2))


def matches_skills(title: str, description: str = "") -> bool:
    combined = (title + " " + description).lower()
    return any(s in combined for s in SKILLS_FILTER)


def scan_lever(company: str) -> list[dict]:
    """Check Lever API for Java jobs at a company. Free, no auth."""
    jobs = []
    try:
        resp = httpx.get(f"https://api.lever.co/v0/postings/{company}?mode=json", timeout=10)
        if resp.status_code != 200:
            return []
        for posting in resp.json():
            title = posting.get("text", "")
            desc = posting.get("descriptionPlain", "") or posting.get("description", "")
            if matches_skills(title, desc):
                jobs.append({
                    "title": title,
                    "company": posting.get("categories", {}).get("team", company),
                    "url": posting.get("applyUrl") or posting.get("hostedUrl", ""),
                    "location": posting.get("categories", {}).get("location", ""),
                    "description": desc[:1000],
                    "source": "lever_api",
                    "ats_type": "lever",
                })
    except Exception:
        pass
    return jobs


def scan_greenhouse(company: str) -> list[dict]:
    """Check Greenhouse API for Java jobs at a company. Free, no auth."""
    jobs = []
    try:
        resp = httpx.get(f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true", timeout=10)
        if resp.status_code != 200:
            return []
        for posting in resp.json().get("jobs", []):
            title = posting.get("title", "")
            desc = posting.get("content", "")
            if matches_skills(title, desc):
                url = posting.get("absolute_url", "")
                job_id = posting.get("id", "")
                # Always use direct Greenhouse URL (company-hosted URLs often need JS)
                if "greenhouse.io" not in url and job_id:
                    url = f"https://job-boards.greenhouse.io/{company}/jobs/{job_id}"
                jobs.append({
                    "title": title,
                    "company": company,
                    "url": url,
                    "location": ", ".join(l.get("name", "") for l in posting.get("location", {}).get("locations", []) if l.get("name")),
                    "description": __import__('html').unescape(re.sub(r'<[^>]+>', '', desc))[:1000],
                    "source": "greenhouse_api",
                    "ats_type": "greenhouse",
                })
    except Exception:
        pass
    return jobs


def discover_company(company_name: str, companies: dict):
    """When we see a new company, try to find their Lever/Greenhouse board."""
    slug = re.sub(r'[^a-z0-9]', '', company_name.lower())
    if slug in companies["lever"] or slug in companies["greenhouse"]:
        return

    # Try Lever
    try:
        resp = httpx.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", timeout=5)
        if resp.status_code == 200 and resp.json():
            companies["lever"].append(slug)
            companies["discovered"].append(f"lever:{slug}")
            return
    except Exception:
        pass

    # Try Greenhouse
    try:
        resp = httpx.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", timeout=5)
        if resp.status_code == 200 and resp.json().get("jobs"):
            companies["greenhouse"].append(slug)
            companies["discovered"].append(f"greenhouse:{slug}")
            return
    except Exception:
        pass

    # Try common variations
    for variant in [slug + "io", slug + "hq", slug + "-jobs", slug + "inc"]:
        try:
            resp = httpx.get(f"https://api.lever.co/v0/postings/{variant}?mode=json", timeout=5)
            if resp.status_code == 200 and resp.json():
                companies["lever"].append(variant)
                companies["discovered"].append(f"lever:{variant}")
                return
        except Exception:
            pass


def scan_ashby(company: str) -> list[dict]:
    """Check Ashby API for jobs. Free, no auth."""
    jobs = []
    try:
        resp = httpx.post(f"https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobBoardWithTeams",
            json={"operationName": "ApiJobBoardWithTeams", "variables": {"organizationHostedJobsPageName": company},
                  "query": "query ApiJobBoardWithTeams($organizationHostedJobsPageName:String!){jobBoard:jobBoardWithTeams(organizationHostedJobsPageName:$organizationHostedJobsPageName){jobs{id title locationName}}}"},
            timeout=10)
        if resp.status_code != 200:
            return []
        data = resp.json().get("data", {}).get("jobBoard", {}).get("jobs", [])
        for posting in data:
            title = posting.get("title", "")
            if matches_skills(title):
                jobs.append({
                    "title": title, "company": company,
                    "url": f"https://jobs.ashbyhq.com/{company}/{posting['id']}",
                    "location": posting.get("locationName", ""),
                    "description": title, "source": "ashby_api", "ats_type": "ashby",
                })
    except Exception:
        pass
    return jobs


def scan_workable(company: str) -> list[dict]:
    """Check Workable API for jobs. Free, no auth."""
    jobs = []
    try:
        resp = httpx.get(f"https://apply.workable.com/api/v1/widget/accounts/{company}", timeout=10)
        if resp.status_code != 200:
            return []
        for posting in resp.json().get("jobs", []):
            title = posting.get("title", "")
            desc = posting.get("description", "")
            if matches_skills(title, desc):
                jobs.append({
                    "title": title, "company": company,
                    "url": f"https://apply.workable.com/{company}/j/{posting.get('shortcode', '')}",
                    "location": posting.get("location", {}).get("city", ""),
                    "description": desc[:1000], "source": "workable_api", "ats_type": "workable",
                })
    except Exception:
        pass
    return jobs


def scan_wellfound() -> list[dict]:
    """Search Wellfound (AngelList) for Java contract jobs via web."""
    jobs = []
    try:
        resp = httpx.get("https://wellfound.com/role/r/java-developer", timeout=10,
                         headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 200 and "java" in resp.text.lower():
            # Extract job links from HTML
            import re
            links = re.findall(r'href="(/jobs/[^"]+)"', resp.text)
            for link in links[:20]:
                jobs.append({
                    "title": "Java Developer", "company": "wellfound",
                    "url": f"https://wellfound.com{link}",
                    "location": "Remote", "description": "",
                    "source": "wellfound", "ats_type": "wellfound",
                })
    except Exception:
        pass
    return jobs


def scan_remotefront() -> list[dict]:
    """Search RemoteFront for Java remote jobs."""
    jobs = []
    try:
        resp = httpx.get("https://remotefront.com/api/jobs?q=java&remote=true", timeout=10,
                         headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 200:
            for posting in resp.json()[:20]:
                title = posting.get("title", "")
                if matches_skills(title, posting.get("description", "")):
                    jobs.append({
                        "title": title, "company": posting.get("company", ""),
                        "url": posting.get("url", ""),
                        "location": "Remote", "description": posting.get("description", "")[:1000],
                        "source": "remotefront", "ats_type": "unknown",
                    })
    except Exception:
        pass
    return jobs


SEED_ASHBY = ["anthropic", "notion", "ramp", "retool", "linear", "vercel", "supabase",
              "resend", "cal-com", "dbt-labs", "airbyte", "temporal", "neon"]
SEED_WORKABLE = ["twilio", "elastic", "n8n", "zapier", "talkdesk", "genesys"]


def scan_all_companies(max_companies: int = 30) -> list[dict]:
    """Scan all known companies for Java jobs. Returns list of jobs."""
    companies = load_companies()
    all_jobs = []
    scanned = 0

    print(f"  Scanning {len(companies['lever'])} Lever + {len(companies['greenhouse'])} Greenhouse companies...")

    # Scan Lever companies
    for company in companies["lever"][:max_companies]:
        jobs = scan_lever(company)
        if jobs:
            all_jobs.extend(jobs)
            print(f"    ✅ Lever/{company}: {len(jobs)} Java jobs")
        scanned += 1
        time.sleep(0.3)  # rate limit

    # Scan Greenhouse companies
    for company in companies["greenhouse"][:max_companies]:
        jobs = scan_greenhouse(company)
        if jobs:
            all_jobs.extend(jobs)
            print(f"    ✅ Greenhouse/{company}: {len(jobs)} Java jobs")
        scanned += 1
        time.sleep(0.3)

    # Scan Ashby companies
    for company in SEED_ASHBY[:max_companies]:
        jobs = scan_ashby(company)
        if jobs:
            all_jobs.extend(jobs)
            print(f"    ✅ Ashby/{company}: {len(jobs)} jobs")
        scanned += 1
        time.sleep(0.3)

    # Scan Workable companies
    for company in SEED_WORKABLE[:max_companies]:
        jobs = scan_workable(company)
        if jobs:
            all_jobs.extend(jobs)
            print(f"    ✅ Workable/{company}: {len(jobs)} jobs")
        scanned += 1
        time.sleep(0.3)

    # Scan Wellfound + RemoteFront
    wf_jobs = scan_wellfound()
    if wf_jobs:
        all_jobs.extend(wf_jobs)
        print(f"    ✅ Wellfound: {len(wf_jobs)} jobs")
    rf_jobs = scan_remotefront()
    if rf_jobs:
        all_jobs.extend(rf_jobs)
        print(f"    ✅ RemoteFront: {len(rf_jobs)} jobs")

    save_companies(companies)

    # Deduplicate by URL
    seen = set()
    unique = []
    for j in all_jobs:
        if j["url"] and j["url"] not in seen:
            seen.add(j["url"])
            unique.append(j)

    print(f"  Scanned {scanned} companies → {len(unique)} Java jobs found")
    print(f"  Discovered companies: {len(companies.get('discovered', []))}")
    return unique
