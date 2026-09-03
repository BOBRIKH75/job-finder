#!/usr/bin/env python3
"""Mine MORE jobs from recruiter emails (their postings) — free, no API.

Recruiters email Bob Java/C2C job postings. Each email = a job (title in subject) + a real
recruiter to reply to. This extracts (title, recruiter_email, company) from recruiter emails,
CV-matches the title, and saves matching ones as leads in data/recruiter_job_leads.json.
The recruiter is added to vendor_list so vendor_outreach sends the CV (reply-to-apply).

Env: GMAIL_USER, GMAIL_APP_PASSWORD.
Run: python3 scripts/jobs_from_recruiter_emails.py
"""
import os, re, json, imaplib, email
from email.header import decode_header
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
LEADS = os.path.join(DATA, 'recruiter_job_leads.json')
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

try:
    from cv_match import should_apply
except Exception:
    try:
        from src.cv_match import should_apply
    except Exception:
        should_apply = None

NOISE = ('indeed', 'dice.com', 'linkedin', 'resend', 'noreply', 'no-reply', 'donotreply',
         'google', 'glassdoor', 'ziprecruiter', 'lensa', 'jobot', 'jobleads', 'haystack',
         'monster', 'mailer', 'notifications', 'alerts', 'aggregated', 'jobalert',
         'careerservice', 'talent.com', 'digest', 'newsletter',
         # marketing/product senders (not recruiters) that leaked in testing:
         'apollo.io', 'dochub', 'loopcv', 'giraffyreach', 'ropes.ai', 'micro1.ai',
         'changelog', 'hello@', 'team+', 'support@', 'nisc.coop')
# the title must look like an actual dev job (not marketing copy that happens to say 'engineer')
ROLE_WORD = re.compile(r'\b(developer|engineer|programmer|architect|sde|full[\s-]?stack|'
                       r'backend|back[\s-]?end|java|spring|software)\b', re.I)
ADDR = re.compile(r'[\w.+-]+@[\w.-]+\.\w+')


def _dec(s):
    return ''.join(t.decode(e or 'utf-8', 'ignore') if isinstance(t, bytes) else t
                   for t, e in decode_header(s or ''))


def _clean_title(subj):
    # recruiter subjects: "GenAI Full-Stack Developer || 100% Remote", "Hiring for X", "Job: X"
    t = re.sub(r'^\s*(re:|fwd:|job[:\-]?|hiring for|urgent[:\-]?|new requirement[:\-]?)\s*', '',
               subj, flags=re.I).strip()
    t = re.split(r'\s*\|\||\s*::+|\s* - ', t)[0].strip()   # take the role part before || / ::
    return t[:90]


def main():
    u, p = os.environ.get('GMAIL_USER', ''), os.environ.get('GMAIL_APP_PASSWORD', '')
    if not u or not p:
        print("no gmail creds"); return
    try:
        leads = json.load(open(LEADS))
    except Exception:
        leads = []
    seen = {l.get('recruiter_email', '') + '|' + l.get('title', '') for l in leads}
    try:
        vendors = json.load(open(VENDOR))
        vemails = {v.get('email', '').lower() for v in vendors}
    except Exception:
        vendors, vemails = [], set()

    print("🔍 Mining jobs from recruiter emails...")
    M = imaplib.IMAP4_SSL('imap.gmail.com'); M.login(u, p); M.select('inbox')
    _, d = M.search(None, 'ALL')
    ids = d[0].split()
    scan = int(os.environ.get('INBOX_SCAN', '300'))
    new_leads, new_vendors = [], []
    for i in ids[-scan:]:
        try:
            _, md = M.fetch(i, '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])')
            m = email.message_from_string(md[0][1].decode('utf-8', 'ignore'))
            frm, subj = _dec(m.get('From')), _dec(m.get('Subject'))
        except Exception:
            continue
        em = ADDR.search(frm)
        if not em:
            continue
        addr = em.group(0).lower()
        if addr in (u.lower(), 'bobrikh75@gmail.com', 'rikhsiboev@gmail.com'):
            continue
        if any(n in addr for n in NOISE):
            continue
        title = _clean_title(subj)
        if len(title) < 6:
            continue
        if not ROLE_WORD.search(title):   # must be an actual dev-role title, not marketing copy
            continue
        # CV-match the title (only keep Java/backend/remote-fit postings)
        if should_apply:
            ok, score, _ = should_apply(title, subj, 'Remote')
            if not ok:
                continue
        key = addr + '|' + title
        if key in seen:
            continue
        seen.add(key)
        company = addr.split('@')[1].split('.')[0].title()
        name = re.sub(r'<.*?>', '', frm).strip().strip('"')
        if '@' in name:
            name = ''
        new_leads.append({'title': title, 'recruiter_email': addr, 'recruiter_name': name,
                          'company': company, 'source': 'recruiter-email',
                          'found': datetime.now().strftime('%Y-%m-%d')})
        # add recruiter to vendor_list so outreach sends the CV (reply-to-apply)
        if addr not in vemails:
            vemails.add(addr)
            new_vendors.append({'name': name or company, 'company': company, 'email': addr,
                                'position': 'recruiter (job posting)', 'source': 'recruiter-email-lead',
                                'last_subject': subj[:60], 'verified': datetime.now().strftime('%Y-%m-%d')})
    M.logout()

    if new_leads:
        leads.extend(new_leads)
        json.dump(leads, open(LEADS, 'w'), indent=2)
    if new_vendors:
        vendors.extend(new_vendors)
        json.dump(vendors, open(VENDOR, 'w'), indent=2)
    print(f"\n📊 {len(new_leads)} NEW job leads from recruiters (CV-matched), "
          f"{len(new_vendors)} new recruiters added for CV outreach")
    for l in new_leads[:20]:
        print(f"  • {l['title'][:50]:50} ← {l['recruiter_email']}")


if __name__ == '__main__':
    main()
