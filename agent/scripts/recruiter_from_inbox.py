#!/usr/bin/env python3
"""Harvest REAL recruiter emails from Bob's inbox — the best free source.

Recruiters who email Bob about Java/C2C roles are REAL people with REAL, verified emails
(they reached out). Far better than guessed role inboxes. This scans Gmail, keeps genuine
recruiter senders (job-content subjects), drops job-board/automated noise, and adds them
to vendor_list.json with the recruiter's name + company (from the email domain).

Env: GMAIL_USER, GMAIL_APP_PASSWORD.
Run: python3 scripts/recruiter_from_inbox.py
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

# Automated / job-board / aggregator senders to EXCLUDE (not real recruiters)
NOISE = ('indeed', 'dice.com', 'linkedin', 'resend', 'noreply', 'no-reply', 'donotreply',
         'do-not-reply', 'google', 'glassdoor', 'ziprecruiter', 'lensa', 'jobot', 'jobleads',
         'haystack', 'giraffyreach', 'monster', 'mailer', 'notifications', 'alerts', 'aggregated',
         'jobalert', 'careerservice', 'updates@', 'noreply@', 'accounts', 'support@', 'info@',
         'talent.com', 'welcome', 'digest', 'newsletter', 'automated')

# Recruiter-signal keywords in subject/from (a real recruiter emailing about a role)
SIGNAL = re.compile(r'java|developer|engineer|opportunity|\brole\b|position|contract|c2c|corp[- ]?to[- ]?corp|'
                    r'requirement|hiring|urgent|w2|full[- ]?stack|backend|spring|microservice',
                    re.I)
ADDR = re.compile(r'[\w.+-]+@[\w.-]+\.\w+')


def _dec(s):
    return ''.join(t.decode(e or 'utf-8', 'ignore') if isinstance(t, bytes) else t
                   for t, e in decode_header(s or ''))


def main():
    u, p = os.environ.get('GMAIL_USER', ''), os.environ.get('GMAIL_APP_PASSWORD', '')
    if not u or not p:
        print("no gmail creds"); return
    try:
        vendors = json.load(open(VENDOR))
    except Exception:
        vendors = []
    existing = {v.get('email', '').lower() for v in vendors}

    print("🔍 Harvesting REAL recruiters from inbox...")
    M = imaplib.IMAP4_SSL('imap.gmail.com'); M.login(u, p); M.select('inbox')
    _, d = M.search(None, 'ALL')
    ids = d[0].split()
    scan = int(os.environ.get('INBOX_SCAN', '300'))
    new = []
    for i in ids[-scan:]:
        try:
            _, md = M.fetch(i, '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])')
            m = email.message_from_string(md[0][1].decode('utf-8', 'ignore'))
            frm = _dec(m.get('From')); subj = _dec(m.get('Subject'))
        except Exception:
            continue
        em = ADDR.search(frm)
        if not em:
            continue
        addr = em.group(0).lower()
        if addr in existing:
            continue
        # skip Bob's own addresses (self-notifications from the bot)
        if addr in (u.lower(), 'bobrikh75@gmail.com', 'rikhsiboev@gmail.com'):
            continue
        if any(n in addr for n in NOISE):
            continue
        if not SIGNAL.search(subj + ' ' + frm):
            continue
        # recruiter name = the display name before <email>
        name = re.sub(r'<.*?>', '', frm).strip().strip('"').strip()
        if '@' in name:
            name = ''
        domain = addr.split('@')[1]
        company = domain.split('.')[0].title()
        existing.add(addr)
        new.append({'name': name, 'company': company, 'email': addr,
                    'position': 'recruiter (emailed Bob)', 'source': 'inbox-harvest',
                    'last_subject': subj[:60], 'verified': datetime.now().strftime('%Y-%m-%d')})
    M.logout()

    if new:
        vendors.extend(new)
        json.dump(vendors, open(VENDOR, 'w'), indent=2)
    print(f"\n📊 {len(new)} REAL recruiters harvested from inbox, vendor list now {len(vendors)}")
    for r in new[:25]:
        print(f"  • {r['email']:40} {('('+r['name']+')') if r['name'] else '':22} {r['last_subject']}")


if __name__ == '__main__':
    main()
