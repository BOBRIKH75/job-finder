#!/usr/bin/env python3
"""REAL-TIME C2C requirement harvester for nvoids.com (job.nvoids.com).

nvoids publishes fresh C2C requirements with the recruiter's email INLINE in each post —
no login, newest-first. Glassdoor/Indeed hide or delay posts; nvoids is live. This pulls
the latest listings, parses each detail page, extracts role + recruiter email + rate +
C2C/employment + skills, filters to Bob's Java/Spring Boot fit, and writes them as
recruiter LEADS the pipeline can act on (email the recruiter the CV, or draft a reply).

Output: appends to agent/data/recruiter_job_leads.json (the GOLD source vendor_outreach
emails FIRST) + agent/data/nvoids_leads.json (full detail for review).

Dedup: agent/data/nvoids_seen.json (job ids already processed).

Usage:
  cd ~/Downloads/CV/job-finder/agent && python3 scripts/harvest_nvoids.py [--pages 3] [--max 120]
"""
import json
import os
import re
import sys
import time
import urllib.request
import ssl

BASE = "https://job.nvoids.com"
LIST_URL = BASE + "/"
DETAIL = BASE + "/j_details.jsp?id={id}&uid={uid}"

DATA = "data" if os.path.isdir("data") else "agent/data"
SEEN_FILE = os.path.join(DATA, "nvoids_seen.json")
LEADS_FILE = os.path.join(DATA, "nvoids_leads.json")
GOLD_FILE = os.path.join(DATA, "recruiter_job_leads.json")

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

# Bob's fit: keep Java/Spring/backend; drop clearly-off stacks.
KEEP = ("java", "spring", "spring boot", "microservice", "backend", "back end",
        "back-end", "kafka", "j2ee", "full stack java", "software engineer")
DROP = (".net", "c#", "dotnet", "salesforce", "servicenow", "pega", "workday",
        "sap ", "oracle apex", "mainframe", "cobol", "python developer",
        "golang", "ruby", "php", "ios ", "android ", "frontend only",
        "data engineer", "data scientist", "qa ", "tester", "business analyst",
        "scrum master", "project manager", "devops engineer", "network engineer")


def _get(url, timeout=20):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:
        return ""


def _load(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(obj, open(path, "w"), indent=2)


def _text(html):
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _email(html, text):
    # plain mailto first (nvoids uses plain mailto), then any @ in text.
    # Skip the site's own address AND Bob's own (his hotlist posts show up in the feed).
    SKIP = ("nvoids.com", "bobrikh75@gmail.com")
    m = re.search(r"mailto:([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})", html)
    if m and not any(s in m.group(1).lower() for s in SKIP):
        return m.group(1).lower()
    cand = [e.lower() for e in
            re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
            if not any(s in e.lower() for s in SKIP)]
    return cand[0] if cand else ""


def _title(text):
    m = re.search(r"(?:Job Title|Position|Role)\s*[-:]\s*([^\n|]{3,70})", text, re.I)
    raw = m.group(1).strip() if m else ""
    if not raw:
        m = re.search(r"(?:Urgent Requirement|Requirement|Hiring(?: for)?)\s*[:\-]?\s*"
                      r"([A-Za-z][\w /.+#-]{3,60}?(?:developer|engineer|architect|lead))",
                      text, re.I)
        raw = m.group(1).strip() if m else ""
    # cut trailing field labels that bleed in (Experience:/Location:/Type:/Duration:)
    raw = re.split(r"\b(?:Experience|Location|Type|Duration|Exp|Rate|Employment)\b",
                   raw, flags=re.I)[0].strip(" -:·|")
    return raw


def _rate(text):
    m = re.search(r"\$?\s?(\d{2,3})\s?[-to/]{1,3}\s?\$?\s?(\d{2,3})\s?(?:/?\s?hr|/hour|per hour)",
                  text, re.I)
    if m:
        return f"${m.group(1)}-{m.group(2)}/hr"
    m = re.search(r"\$?\s?(\d{2,3})\s?(?:/?\s?hr|/hour|per hour)", text, re.I)
    return f"${m.group(1)}/hr" if m else ""


def _location(text):
    m = re.search(r"Location\s*[-:]\s*([^\n|]{2,40})", text, re.I)
    return m.group(1).strip() if m else ("Remote" if "remote" in text.lower() else "")


def _company(text, email):
    m = re.search(r"(?:at|from|@)\s+([A-Z][\w& ]{2,40}(?:Inc|LLC|Technologies|Solutions|Systems|Consulting|World))",
                  text)
    if m:
        return m.group(1).strip()
    return email.split("@")[-1].split(".")[0].title() if email else ""


def _fits(title, text):
    blob = (title + " " + text[:600]).lower()
    if any(d in blob for d in DROP):
        return False
    return any(k in blob for k in KEEP)


def _is_bodyshop(email, company, text):
    """Business-signal check: is this an offshore C2C bench-shop (low value) vs a real
    US-relevant recruiter? NOT national origin — signals only. Returns True to DROP."""
    e, comp, t = (email or "").lower(), (company or "").lower(), (text or "").lower()
    local = e.split("@")[0]
    neg = 0
    # bench-sales / mass local parts
    if any(local.startswith(b) or local == b for b in
           ("benchsales", "bench", "hotlist", "marketing", "resumes", "submissions",
            "requirements", "req", "consultants", "recruit", "anilrecruit")):
        neg += 1
    # free webmail recruiter (individual bench rep, not a firm)
    if e.split("@")[-1] in ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com"):
        neg += 1
    # +91 / whatsapp / visa-status language = classic C2C bench-shop post
    if re.search(r"\+?91[\s\-]?\d{10}\b", t) or "whatsapp" in t:
        neg += 1
    if any(p in t for p in ("opt", "cpt", "h1b", "h-1b", "ept", "gc-ept",
                            "share your hotlist", "send hotlist", "bench ",
                            "prime vendor list", "us citizen or green card only",
                            "passport number", "last 4 digit", "date of birth")):
        neg += 1
    # multiple visa categories listed (USC/GC/H1B/OPT) = body-shop boilerplate
    visa_terms = sum(1 for v in ("usc", "gc", "h1b", "opt", "cpt", "ead") if v in t)
    if visa_terms >= 3:
        neg += 1
    return neg >= 2   # 2+ negative signals = drop (avoid false drops on real firms)


def main():
    pages = 3
    maxn = int(os.environ.get("NVOIDS_MAX", "120"))
    if "--pages" in sys.argv:
        try: pages = int(sys.argv[sys.argv.index("--pages") + 1])
        except Exception: pass
    if "--max" in sys.argv:
        try: maxn = int(sys.argv[sys.argv.index("--max") + 1])
        except Exception: pass

    seen = set(_load(SEEN_FILE, []))
    gold = _load(GOLD_FILE, [])
    gold_emails = {(g.get("recruiter_email") or "").lower() for g in gold}
    nleads = _load(LEADS_FILE, [])

    # 1) pull the listing (newest first), collect id+uid pairs
    listing = _get(LIST_URL)
    pairs = re.findall(r'j_details\.jsp\?id=(\d+)&uid=([a-f0-9]+)', listing)
    # de-dup preserving order (newest first), cap
    uniq, order = {}, []
    for jid, uid in pairs:
        if jid not in uniq:
            uniq[jid] = uid; order.append(jid)
    order = order[:maxn]
    print(f"🔎 nvoids: {len(order)} listings on the front page (newest first)")

    new_fit = 0
    checked = 0
    for jid in order:
        if jid in seen:
            continue
        checked += 1
        html = _get(DETAIL.format(id=jid, uid=uniq[jid]))
        if not html:
            continue
        text = _text(html)
        title = _title(text)
        if not _fits(title or "", text):
            seen.add(jid)
            continue
        email = _email(html, text)
        if not email:
            seen.add(jid)
            continue
        company = _company(text, email)
        bodyshop = _is_bodyshop(email, company, text)
        lead = {
            "id": jid,
            "title": title or "Java Developer (nvoids)",
            "recruiter_email": email,
            "company": company,
            "rate": _rate(text),
            "location": _location(text),
            "source": "nvoids",
            "bodyshop": bodyshop,
            "url": DETAIL.format(id=jid, uid=uniq[jid]),
            "snippet": text[:300],
            "harvested": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        nleads.append(lead)
        seen.add(jid)
        if bodyshop:
            # low-value offshore C2C bench desk — keep in nvoids_leads for reference,
            # but DO NOT add to gold leads (gold = emailed first). Skip the queue-jump.
            print(f"  🌍 skip body-shop: {title[:38]:40s} {email}")
            continue
        # US-relevant recruiter → add to GOLD leads (emailed first, CV attached)
        if email not in gold_emails:
            gold.append({
                "recruiter_email": email,
                "recruiter_name": company or email.split("@")[0].title(),
                "company": company,
                "role": lead["title"],
                "source": "nvoids",
            })
            gold_emails.add(email)
        new_fit += 1
        print(f"  ✅ {title[:38]:40s} {email:34s} {lead['rate']} {lead['location'][:18]}")
        time.sleep(0.4)   # polite

    # keep files bounded
    nleads = nleads[-500:]
    _save(SEEN_FILE, sorted(seen)[-5000:])
    _save(LEADS_FILE, nleads)
    _save(GOLD_FILE, gold)

    print(f"\n📊 nvoids harvest: checked {checked} new, kept {new_fit} Java/C2C-fit leads")
    print(f"   → {new_fit} new recruiter emails added to recruiter_job_leads.json "
          f"(vendor_outreach will email them FIRST, CV attached)")
    print(f"   → full details in {LEADS_FILE}")


if __name__ == "__main__":
    main()
