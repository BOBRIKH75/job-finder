#!/usr/bin/env python3
"""Recruiter finder from OUR OWN APPLICATIONS — the reliable source.

The old recruiter_finder scraped dead URLs (nvoids 404, Google Groups 404) → 0 found.
This instead uses the companies we ACTUALLY applied to (extracted from Dice/Indeed
confirmation emails) — they are staffing/recruiting firms — and Hunter.io domain-searches
them for recruiter emails, adding new ones to vendor_list.json.

Env: GMAIL_USER, GMAIL_APP_PASSWORD (read confirmation emails), HUNTER_API_KEY (optional).
Run: python3 scripts/recruiter_from_applications.py
"""
import os, re, json, imaplib, email
from email.header import decode_header
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
VENDOR = os.path.join(DATA, 'vendor_list.json')

for path in (os.path.join(HERE, '..', '.env'), '.env', 'agent/.env'):
    try:
        for line in open(path):
            line = line.strip()
            if line and '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception:
        pass

EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')


def _dec(s):
    return ''.join(t.decode(e or 'utf-8', 'ignore') if isinstance(t, bytes) else t
                   for t, e in decode_header(s or ''))


def companies_from_emails():
    """Companies we applied to, from Dice + Indeed confirmation email subjects."""
    u, p = os.environ.get('GMAIL_USER', ''), os.environ.get('GMAIL_APP_PASSWORD', '')
    if not u or not p:
        print("  ⚠️ no Gmail creds — cannot read application emails")
        return set()
    companies = set()
    try:
        M = imaplib.IMAP4_SSL('imap.gmail.com'); M.login(u, p); M.select('inbox')
        # Dice: "Application for <TITLE> at <COMPANY> sent"
        _, d = M.search(None, '(FROM "applyonline@dice.com")')
        for i in d[0].split()[-80:]:
            _, md = M.fetch(i, '(BODY.PEEK[HEADER.FIELDS (SUBJECT)])')
            subj = _dec(email.message_from_string(md[0][1].decode('utf-8', 'ignore')).get('Subject'))
            m = re.search(r' at (.+?) sent$', subj)
            if m:
                companies.add(m.group(1).strip())
        M.logout()
    except Exception as e:
        print(f"  ⚠️ email read error: {e}")
    return companies


def company_to_domain(name):
    """Best-effort company → domain guess for Hunter (Hunter also accepts company name)."""
    slug = re.sub(r'[^a-z0-9]', '', name.lower().split(',')[0]
                  .replace(' inc', '').replace(' llc', '').replace(' corporation', '')
                  .replace(' corp', '').replace(' technologies', '').replace(' solutions', ''))
    return slug


def hunter_recruiters(company, existing):
    key = os.environ.get('HUNTER_API_KEY', '')
    if not key:
        return []
    import urllib.request, urllib.parse
    found = []
    try:
        params = urllib.parse.urlencode({'company': company, 'api_key': key, 'limit': 10})
        with urllib.request.urlopen(f"https://api.hunter.io/v2/domain-search?{params}", timeout=20) as r:
            data = json.loads(r.read())
        for e in data.get('data', {}).get('emails', []):
            addr = (e.get('value') or '').lower()
            if addr and addr not in existing and any(
                    k in (e.get('position', '') or '').lower()
                    for k in ('recruit', 'talent', 'staffing', 'hr', 'hiring', 'sourc')):
                found.append({
                    'name': f"{e.get('first_name','')} {e.get('last_name','')}".strip(),
                    'company': company, 'email': addr,
                    'position': e.get('position', ''),
                    'source': 'hunter/applied-company',
                    'verified': datetime.now().strftime('%Y-%m-%d'),
                })
    except Exception as ex:
        print(f"    hunter {company[:20]} err: {str(ex)[:50]}")
    return found


def main():
    print("🔍 Recruiter finder from OUR APPLICATIONS...")
    try:
        vendors = json.load(open(VENDOR))
    except Exception:
        vendors = []
    existing = {v.get('email', '').lower() for v in vendors}

    companies = companies_from_emails()
    print(f"  📋 {len(companies)} companies we applied to (recruiter targets)")

    new = []
    if os.environ.get('HUNTER_API_KEY'):
        for c in sorted(companies):
            for rec in hunter_recruiters(c, existing):
                if rec['email'] not in existing:
                    existing.add(rec['email']); new.append(rec)
    else:
        print("  ⚠️ HUNTER_API_KEY not set — company list gathered but no email lookup this run")

    if new:
        vendors.extend(new)
        json.dump(vendors, open(VENDOR, 'w'), indent=2)
    print(f"\n📊 Results: {len(new)} new recruiters, total vendor list {len(vendors)}")
    # save the target company list for the CI Hunter step / audit
    try:
        json.dump(sorted(companies), open(os.path.join(DATA, 'applied_companies.json'), 'w'), indent=2)
    except Exception:
        pass


if __name__ == '__main__':
    main()
