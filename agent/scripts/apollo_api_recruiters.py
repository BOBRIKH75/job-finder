#!/usr/bin/env python3
"""
Apollo recruiter finder — API-BASED (no cookies, no browser, no TTL, no ban risk).

WHY THIS REPLACES apollo_scraper.py:
  The old scraper used Chrome cookies + a 7-day TTL refresh that CANNOT work on macOS CI —
  background jobs can't decrypt Chrome's cookie store (needs Keychain/GUI). Every scheduled
  refresh failed with "No Apollo cookies found (or all encrypted)". The Apollo REST API needs
  ONLY the APOLLO_API_KEY secret — no cookies to expire, nothing to refresh.

GOAL (Bob): job -> company name -> that company's recruiters/HR -> emails -> outreach.
  This searches Apollo BY COMPANY for recruiter/HR/talent titles and reveals emails.

Env: APOLLO_API_KEY (required), GMAIL_USER/GMAIL_APP_PASSWORD (to source company names).
Free tier is limited (~75-100 reveals/mo) — capped per run + deduped so it lasts.
"""
import os, re, json, time, imaplib, email, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
VENDOR_FILE = DATA / "vendor_list.json"
SEEN_FILE = DATA / "apollo_api_seen.json"

API = "https://api.apollo.io/v1/mixed_people/search"
TITLES = ["Technical Recruiter", "IT Recruiter", "Recruiter", "Talent Acquisition",
          "Sr. Recruiter", "Staffing Manager", "HR Manager", "Human Resources"]
PER_RUN_COMPANY_CAP = int(os.environ.get("APOLLO_COMPANY_CAP", "8"))   # protect free credits
NOISE = ("indeed", "dice.com", "linkedin", "ziprecruiter", "glassdoor", "lensa", "monster",
         "resend", "bobrikh75", "google", "greenhouse", "lever", "noreply", "notifications",
         "mailer", "apollo", "hunter", "github", "okta")


def _load(p, default):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def _env():
    envf = HERE.parent / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def companies_from_gmail():
    user, pw = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
    if not user or not pw:
        return []
    M = imaplib.IMAP4_SSL("imap.gmail.com")
    M.login(user, pw)
    names = {}
    for box in ("INBOX", '"[Gmail]/All Mail"'):
        try:
            M.select(box)
        except Exception:
            continue
        typ, d = M.search(None, "ALL")
        for i in d[0].split()[-400:]:
            try:
                typ, md = M.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
                msg = email.message_from_string(md[0][1].decode(errors="ignore"))
                frm = (msg.get("From") or "").lower()
                m = re.search(r"[\w.+-]+@([\w.-]+)", frm)
                dom = m.group(1) if m else ""
                if dom and not any(n in dom for n in NOISE):
                    names[dom.split(".")[0].title()] = dom
            except Exception:
                continue
    M.logout()
    return list(names.items())


def apollo_search(domain, key):
    payload = json.dumps({
        "q_organization_domains": domain,
        "person_titles": TITLES,
        "page": 1, "per_page": 10,
        "reveal_personal_emails": True,
    }).encode()
    req = urllib.request.Request(API, data=payload, headers={
        "Content-Type": "application/json", "Cache-Control": "no-cache",
        "X-Api-Key": key, "Accept": "application/json",
    })
    try:
        r = json.load(urllib.request.urlopen(req, timeout=25))
        return r.get("people", []) or r.get("contacts", [])
    except Exception as e:
        print(f"    apollo err {domain}: {str(e)[:80]}")
        return []


def main():
    _env()
    key = os.environ.get("APOLLO_API_KEY", "")
    if not key:
        print("APOLLO_API_KEY not set — cannot run"); return
    print("Apollo recruiter finder (API — no cookies/TTL/ban)")

    vendors = _load(VENDOR_FILE, [])
    if not isinstance(vendors, list):
        vendors = vendors.get("vendors", []) if isinstance(vendors, dict) else []
    existing = {(v.get("email") or "").lower() for v in vendors}
    seen = set(_load(SEEN_FILE, []))

    companies = companies_from_gmail()
    print(f"  {len(companies)} companies from Gmail; capping {PER_RUN_COMPANY_CAP}/run for free credits")

    added = done = 0
    for name, domain in companies:
        if done >= PER_RUN_COMPANY_CAP:
            break
        if domain in seen:
            continue
        seen.add(domain)
        done += 1
        people = apollo_search(domain, key)
        for p in people:
            em = (p.get("email") or "").strip().lower()
            if not em or "@" not in em or "email_not_unlocked" in em or em in existing:
                continue
            existing.add(em)
            vendors.append({
                "name": name,
                "email": em,
                "person": p.get("name", ""),
                "position": p.get("title", "recruiter"),
                "source": "apollo/api-by-company",
                "domain": domain,
            })
            added += 1
        time.sleep(1.5)

    VENDOR_FILE.write_text(json.dumps(vendors, indent=2))
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2))
    print(f"  added {added} NAMED recruiters w/ real emails (total {len(vendors)})")


if __name__ == "__main__":
    main()
