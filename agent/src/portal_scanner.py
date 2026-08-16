"""Company portal scanner — checks career pages via free APIs, grows company list daily.

Flow:
1. Load company list (seed + learned)
2. For each company, check Lever API and Greenhouse API
3. Filter jobs matching Java/Spring Boot/Kafka skills
4. When agent applies anywhere, extract company → add to list
5. List grows every day automatically

No browser needed — pure API calls, no CAPTCHA.
"""
import json, random, re, time
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


def scan_remoteok() -> list[dict]:
    """Search RemoteOK via their public JSON API (free, no auth)."""
    jobs = []
    try:
        resp = httpx.get(
            "https://remoteok.com/api?tag=java",
            headers={"User-Agent": "Mozilla/5.0 (compatible; job-agent/1.0)"},
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        for item in data[1:]:  # first item is API metadata
            if not isinstance(item, dict):
                continue
            title = item.get("position", "")
            desc = item.get("description", "")
            if not matches_skills(title, desc):
                continue
            job_id = item.get("id", "")
            url = item.get("url", "") or (f"https://remoteok.com/remote-jobs/{job_id}" if job_id else "")
            if not url:
                continue
            jobs.append({
                "title": title,
                "company": item.get("company", ""),
                "url": url,
                "location": "Remote",
                "description": desc[:1000],
                "source": "remoteok",
                "ats_type": "unknown",
            })
    except Exception as e:
        print(f"    RemoteOK scan failed: {e}")
    return jobs


def scan_weworkremotely() -> list[dict]:
    """Search We Work Remotely via their public RSS feed (backend jobs category)."""
    import xml.etree.ElementTree as ET
    jobs = []
    try:
        resp = httpx.get(
            "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)
        channel = root.find("channel")
        if not channel:
            return []
        for item in channel.findall("item"):
            title = item.findtext("title", "")
            desc = item.findtext("description", "") or ""
            link = item.findtext("link", "")
            if not link or not matches_skills(title, desc):
                continue
            # WWR puts "Company: Title" in the title field
            company = ""
            if ": " in title:
                parts = title.split(": ", 1)
                company, title = parts[0].strip(), parts[1].strip()
            jobs.append({
                "title": title,
                "company": company,
                "url": link,
                "location": "Remote",
                "description": desc[:1000],
                "source": "weworkremotely",
                "ats_type": "unknown",
            })
    except Exception as e:
        print(f"    WeWorkRemotely scan failed: {e}")
    return jobs


def scan_ziprecruiter() -> list[dict]:
    """Search ZipRecruiter for Java contract jobs via python-jobspy."""
    jobs = []
    try:
        from jobspy import scrape_jobs
        df = scrape_jobs(
            site_name=["zip_recruiter"],
            search_term="java backend developer",
            location="Remote",
            results_wanted=30,
            job_type="contract",
            hours_old=48,
        )
        for _, row in df.iterrows():
            title = str(row.get("title", ""))
            desc = str(row.get("description", ""))
            if not matches_skills(title, desc):
                continue
            url = str(row.get("job_url", ""))
            if not url or url == "nan":
                continue
            jobs.append({
                "title": title,
                "company": str(row.get("company", "")),
                "url": url,
                "location": str(row.get("location", "")),
                "description": desc[:1000],
                "source": "ziprecruiter",
                "ats_type": "unknown",
            })
    except Exception as e:
        print(f"    ZipRecruiter scan failed: {e}")
    return jobs


def scan_remotive() -> list[dict]:
    """Search Remotive via their free public JSON API (software-dev category)."""
    jobs = []
    try:
        resp = httpx.get(
            "https://remotive.com/api/remote-jobs?category=software-dev&limit=50",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        for item in resp.json().get("jobs", []):
            title = item.get("title", "")
            desc = item.get("description", "")
            url = item.get("url", "")
            if not url or not matches_skills(title, desc):
                continue
            jobs.append({
                "title": title,
                "company": item.get("company_name", ""),
                "url": url,
                "location": item.get("candidate_required_location", "Remote"),
                "description": desc[:1000],
                "source": "remotive",
                "ats_type": "unknown",
            })
    except Exception as e:
        print(f"    Remotive scan failed: {e}")
    return jobs


def scan_himalayas() -> list[dict]:
    """Search Himalayas via their free public JSON API."""
    jobs = []
    try:
        resp = httpx.get(
            "https://himalayas.app/jobs/api?q=java&limit=50",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        for item in resp.json().get("jobs", []):
            title = item.get("title", "")
            desc = item.get("description", "")
            url = item.get("applicationUrl", "") or item.get("url", "")
            if not url or not matches_skills(title, desc):
                continue
            jobs.append({
                "title": title,
                "company": item.get("companyName", ""),
                "url": url,
                "location": item.get("location", "Remote"),
                "description": desc[:1000],
                "source": "himalayas",
                "ats_type": "unknown",
            })
    except Exception as e:
        print(f"    Himalayas scan failed: {e}")
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

    # Scan Wellfound
    wf_jobs = scan_wellfound()
    if wf_jobs:
        all_jobs.extend(wf_jobs)
        print(f"    ✅ Wellfound: {len(wf_jobs)} jobs")

    # RemoteOK — free public JSON API
    rok_jobs = scan_remoteok()
    if rok_jobs:
        all_jobs.extend(rok_jobs)
        print(f"    ✅ RemoteOK: {len(rok_jobs)} jobs")
    time.sleep(random.uniform(1.0, 2.0))

    # We Work Remotely — RSS feed (backend category)
    wwr_jobs = scan_weworkremotely()
    if wwr_jobs:
        all_jobs.extend(wwr_jobs)
        print(f"    ✅ WeWorkRemotely: {len(wwr_jobs)} jobs")
    time.sleep(random.uniform(1.0, 2.0))

    # ZipRecruiter — python-jobspy (contract filter)
    zr_jobs = scan_ziprecruiter()
    if zr_jobs:
        all_jobs.extend(zr_jobs)
        print(f"    ✅ ZipRecruiter: {len(zr_jobs)} jobs")
    time.sleep(random.uniform(1.0, 2.0))

    # Remotive — free public JSON API (software-dev category)
    rem_jobs = scan_remotive()
    if rem_jobs:
        all_jobs.extend(rem_jobs)
        print(f"    ✅ Remotive: {len(rem_jobs)} jobs")
    time.sleep(random.uniform(1.0, 2.0))

    # Himalayas — free public JSON API
    him_jobs = scan_himalayas()
    if him_jobs:
        all_jobs.extend(him_jobs)
        print(f"    ✅ Himalayas: {len(him_jobs)} jobs")

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
