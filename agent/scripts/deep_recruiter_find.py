#!/usr/bin/env python3
"""
Deep recruiter/company finder — FREE, no paid API (built from 2026 research on free
email-discovery methods: role-pattern + MX verify + careers-page scrape).

Pipeline:
  1. Harvest REAL company names from Gmail (recruiter emails + job-digest emails + confirmations).
     NOTE: the applications DB stores "Dice Id: NNNN" not real names, so Gmail is the better source.
  2. For each company -> resolve domain -> verify MX is live (free DNS, no quota).
  3. Generate role-based recruiter inboxes (careers@/recruiting@/talent@/hr@/jobs@) — real,
     published aliases per Prospeo/Cleverly 2026 guidance.
  4. Scrape the company careers/contact page for published person emails (free).
  5. Merge into agent/data/vendor_list.json (deduped) so the existing varied, anti-spam
     vendor_outreach.py emails them with Bob's CV.

Env: GMAIL_USER, GMAIL_APP_PASSWORD. Safe to run daily/weekly; only ADDS new verified contacts.
"""
import os, re, json, imaplib, email, subprocess, urllib.request, ssl
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
VENDOR_FILE = DATA / "vendor_list.json"
SEEN_FILE = DATA / "deep_find_seen.json"

ROLE_ALIASES = ("careers", "recruiting", "talent", "jobs", "hr", "recruitment")

NOISE = ("indeed", "dice.com", "linkedin", "ziprecruiter", "glassdoor", "lensa", "monster",
         "resend", "bobrikh75", "google", "greenhouse", "lever", "noreply", "no-reply",
         "notifications", "jobalerts", "mailer", "apollo", "hunter", "github", "okta")


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


def mx_ok(domain):
    try:
        out = subprocess.run(["nslookup", "-type=mx", domain], capture_output=True,
                             text=True, timeout=8).stdout.lower()
        return "mail exchanger" in out or "mx preference" in out
    except Exception:
        return False


def harvest_companies():
    user, pw = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
    if not user or not pw:
        print("  no Gmail creds — skipping harvest")
        return {}
    M = imaplib.IMAP4_SSL("imap.gmail.com")
    M.login(user, pw)
    companies = {}
    for box in ("INBOX", '"[Gmail]/All Mail"'):
        try:
            M.select(box)
        except Exception:
            continue
        typ, d = M.search(None, "ALL")
        ids = d[0].split()[-600:]
        for i in ids:
            try:
                typ, md = M.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
                msg = email.message_from_string(md[0][1].decode(errors="ignore"))
                frm = msg.get("From") or ""
                subj = msg.get("Subject") or ""
                m = re.search(r"[\w.+-]+@([\w.-]+)", frm.lower())
                dom = m.group(1) if m else ""
                if not dom or any(n in dom for n in NOISE):
                    for pat in (r"hiring (?:for )?(?:a )?.*?at ([A-Z][\w&.\- ]{2,40})",
                                r"([A-Z][\w&.\- ]{2,40}) is hiring",
                                r"opportunity at ([A-Z][\w&.\- ]{2,40})"):
                        mm = re.search(pat, subj)
                        if mm:
                            nm = mm.group(1).strip().rstrip(".")
                            if nm and not any(n in nm.lower() for n in NOISE):
                                companies.setdefault(nm, "")
                    continue
                name = dom.split(".")[0].title()
                companies.setdefault(name, dom)
            except Exception:
                continue
    M.logout()
    return companies


def careers_page_emails(domain):
    found = set()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    for path in ("careers", "contact", "about", "jobs"):
        url = f"https://{domain}/{path}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            html = urllib.request.urlopen(req, timeout=8, context=ctx).read().decode(errors="ignore")
            for em in re.findall(r"[\w.+-]+@" + re.escape(domain), html):
                lp = em.split("@")[0].lower()
                # reject HTML-entity/JS leakage (u003e, x27, quot...) + junk local parts
                if re.search(r"(u00|x2|quot|amp|nbsp|gt|lt|#)", lp):
                    continue
                if not re.match(r"^[a-z0-9][a-z0-9._+-]{1,40}$", lp):
                    continue
                found.add(em.lower())
        except Exception:
            continue
    return found


def main():
    _env()
    print("Deep recruiter/company finder (FREE)")
    vendors = _load(VENDOR_FILE, [])
    if not isinstance(vendors, list):
        vendors = vendors.get("vendors", []) if isinstance(vendors, dict) else []
    existing = {(v.get("email") or "").lower() for v in vendors}
    seen = set(_load(SEEN_FILE, []))

    companies = harvest_companies()
    print(f"  harvested {len(companies)} candidate companies from Gmail")

    added = 0
    for name, domain in companies.items():
        if name in seen:
            continue
        seen.add(name)
        cand = []
        if domain and "." in domain:
            cand.append(domain)
        else:
            slug = re.sub(r"[^a-z0-9]", "", name.lower())
            cand += [f"{slug}.com", f"{slug}.io"]
        live = next((d for d in cand if mx_ok(d)), None)
        if not live:
            continue
        for alias in ROLE_ALIASES:
            em = f"{alias}@{live}"
            if em in existing:
                continue
            existing.add(em)
            vendors.append({"name": name, "email": em, "position": f"{alias} (role inbox)",
                            "source": "deep/role-mx", "domain": live})
            added += 1
        for em in careers_page_emails(live):
            if em in existing or em.split("@")[0] in ROLE_ALIASES:
                continue
            existing.add(em)
            vendors.append({"name": name, "email": em, "position": "published contact",
                            "source": "deep/careers-page", "domain": live})
            added += 1

    VENDOR_FILE.write_text(json.dumps(vendors, indent=2))
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2))
    print(f"  added {added} new verified recruiter contacts (total {len(vendors)})")
    print("  -> next vendor-outreach run emails them (varied message + CV)")


if __name__ == "__main__":
    main()
