"""LinkedIn Recruiter Finder — search companies, guess emails, verify via DNS MX + SMTP."""

import dns.resolver
import smtplib
import socket
import subprocess
import sys
import re
import json
import os
from typing import Optional

# USA states/cities for location filtering
USA_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}
USA_KEYWORDS = {
    "united states", "usa", "u.s.", "remote", "new york", "los angeles", "chicago",
    "houston", "phoenix", "philadelphia", "san antonio", "san diego", "dallas",
    "san jose", "austin", "jacksonville", "san francisco", "columbus", "charlotte",
    "indianapolis", "seattle", "denver", "washington", "boston", "nashville",
    "baltimore", "oklahoma city", "portland", "las vegas", "memphis", "louisville",
    "milwaukee", "albuquerque", "tucson", "fresno", "sacramento", "mesa", "atlanta",
    "kansas city", "colorado springs", "raleigh", "omaha", "miami", "tampa",
    "minneapolis", "cleveland", "pittsburgh", "detroit", "st. louis", "orlando",
}


def is_usa_based(location: str) -> bool:
    """Filter non-USA locations."""
    if not location:
        return False
    loc = location.lower().strip()
    # Reject known non-USA
    non_usa = {"india", "bangalore", "hyderabad", "mumbai", "pune", "chennai", "delhi",
               "noida", "gurgaon", "kolkata", "canada", "uk", "london", "toronto",
               "singapore", "australia", "germany", "france", "netherlands", "ireland"}
    if any(x in loc for x in non_usa):
        return False
    # Check for USA indicators
    if any(x in loc for x in USA_KEYWORDS):
        return True
    # Check state abbreviations (e.g., "Denver, CO" or "NY")
    parts = [p.strip().upper() for p in loc.replace(",", " ").split()]
    return any(p in USA_STATES for p in parts)


def verify_domain_mx(domain: str) -> bool:
    """Check if domain has MX records (accepts email)."""
    try:
        answers = dns.resolver.resolve(domain, "MX")
        return len(answers) > 0
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers,
            dns.resolver.LifetimeTimeout, Exception):
        return False


def verify_email_smtp(email: str) -> bool:
    """SMTP verification — connect to MX, check if mailbox exists. Returns True if not rejected."""
    domain = email.split("@")[1]
    try:
        mx_records = dns.resolver.resolve(domain, "MX")
        mx_host = str(sorted(mx_records, key=lambda r: r.preference)[0].exchange).rstrip(".")
    except Exception:
        return False
    try:
        with smtplib.SMTP(mx_host, 25, timeout=10) as smtp:
            smtp.helo("gmail.com")
            smtp.mail("test@gmail.com")
            code, _ = smtp.rcpt(email)
            return code == 250
    except (smtplib.SMTPException, socket.timeout, socket.error, OSError):
        # Many servers block VRFY/RCPT — treat connection failure as "maybe valid"
        return True


def guess_email(first: str, last: str, domain: str) -> list[str]:
    """Generate common email patterns for a person at a company domain."""
    f = first.lower().strip()
    l = last.lower().strip()
    return [
        f"{f}.{l}@{domain}",
        f"{f}{l}@{domain}",
        f"{f[0]}{l}@{domain}",
        f"{f}_{l}@{domain}",
        f"{f[0]}.{l}@{domain}",
        f"{l}.{f}@{domain}",
        f"{f}@{domain}",
    ]


def _read_chrome_tab_applescript(url: str) -> str:
    """Open URL in Chrome tab 3 and read content via AppleScript (local only)."""
    script = f'''
    tell application "Google Chrome"
        set tabURL to URL of tab 3 of front window
        set URL of tab 3 of front window to "{url}"
        delay 3
        set pageText to execute tab 3 of front window javascript "document.body.innerText"
        return pageText
    end tell
    '''
    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
        return result.stdout
    except Exception:
        return ""


def _is_ci() -> bool:
    return os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true"


def search_recruiters_by_company(company: str) -> list[dict]:
    """Search LinkedIn for recruiters at a company. Returns list of {name, company, location, title}."""
    url = f"https://www.linkedin.com/search/results/people/?keywords=recruiter%20{company}&origin=GLOBAL_SEARCH_HEADER"

    if _is_ci():
        # In CI, use Google search as fallback (no login needed)
        return _search_recruiters_google(company)

    # Local: use Chrome AppleScript
    text = _read_chrome_tab_applescript(url)
    return _parse_linkedin_people_results(text, company)


def _search_recruiters_google(company: str) -> list[dict]:
    """Fallback: Google search for LinkedIn recruiter profiles."""
    try:
        from jobspy import scrape_jobs
        # jobspy searches job boards, not recruiter profiles — limited fallback
        return []
    except ImportError:
        return []


def _parse_linkedin_people_results(text: str, company: str) -> list[dict]:
    """Parse LinkedIn people search results from page text."""
    results = []
    if not text:
        return results
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # LinkedIn people results show: Name\nTitle\nLocation
        if any(kw in line.lower() for kw in ["recruiter", "talent", "staffing", "hiring"]):
            # Look backwards for name
            name = lines[i - 1].strip() if i > 0 else ""
            title = line
            location = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if name and len(name.split()) >= 2 and len(name) < 40:
                results.append({
                    "name": name,
                    "company": company,
                    "location": location,
                    "title": title,
                })
        i += 1
    return results


def search_companies_hiring(keywords: str = "Java Spring Boot") -> list[str]:
    """Find companies with active Java job postings."""
    if _is_ci():
        try:
            from jobspy import scrape_jobs
            jobs = scrape_jobs(site_name=["indeed", "linkedin"], search_term=keywords,
                              location="USA", results_wanted=20)
            companies = list(set(jobs["company"].dropna().tolist()))
            return [c for c in companies if len(c) > 2][:15]
        except Exception:
            pass

    # Local: read from found_jobs.json if available
    jobs_file = os.path.join(os.path.dirname(__file__), "found_jobs.json")
    if os.path.exists(jobs_file):
        try:
            with open(jobs_file) as f:
                jobs = json.load(f)
            companies = list(set(j.get("company", "") for j in jobs if j.get("company")))
            return [c for c in companies if len(c) > 2][:15]
        except Exception:
            pass
    return []


def _company_to_domain(company: str) -> Optional[str]:
    """Guess company email domain from name."""
    # Common mappings
    known = {
        "collabera": "collabera.com",
        "teksystems": "teksystems.com",
        "pyramid consulting": "pyramidci.com",
        "mastech": "mastechdigital.com",
        "skiltrek": "skiltrek.com",
        "amerit consulting": "ameritconsulting.com",
    }
    lower = company.lower().strip()
    if lower in known:
        return known[lower]
    # Default: remove spaces, add .com
    clean = re.sub(r"[^a-z0-9]", "", lower)
    if clean:
        return f"{clean}.com"
    return None


def find_and_verify_recruiters(companies: list[str]) -> list[dict]:
    """Full pipeline: search recruiters at companies, filter USA, guess+verify emails."""
    verified = []
    for company in companies:
        recruiters = search_recruiters_by_company(company)
        domain = _company_to_domain(company)
        if not domain or not verify_domain_mx(domain):
            continue
        for rec in recruiters:
            if not is_usa_based(rec.get("location", "")):
                continue
            name_parts = rec["name"].split()
            if len(name_parts) < 2:
                continue
            first, last = name_parts[0], name_parts[-1]
            emails = guess_email(first, last, domain)
            for email in emails[:3]:  # Try top 3 patterns
                if verify_email_smtp(email):
                    rec["email"] = email
                    rec["domain"] = domain
                    verified.append(rec)
                    break
    return verified


if __name__ == "__main__":
    # Quick test
    print(f"MX check collabera.com: {verify_domain_mx('collabera.com')}")
    print(f"Email patterns: {guess_email('John', 'Smith', 'collabera.com')}")
    print(f"USA check 'Denver, CO': {is_usa_based('Denver, CO')}")
    print(f"USA check 'Bangalore, India': {is_usa_based('Bangalore, India')}")
