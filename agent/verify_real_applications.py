#!/usr/bin/env python3
"""Ground-truth REAL application count — reads Gmail for actual employer confirmations,
NOT the local dedup caches (which count 'already applied' + processed jobs, not submits).

This is the honest answer to "how many jobs did I REALLY apply to with confirmation?"

Signals it counts (real emails):
  - Dice:       FROM applyonline@dice.com  "Application for <title> at <company> sent"
  - Indeed:     FROM indeedapply@indeed.com / indeed.com  "application" / "submitted"
  - LinkedIn:   FROM jobs-noreply@linkedin.com  "your application was sent"
  - Greenhouse: "thank you for applying" / "application received" (varies by company)

Usage:
  cd ~/Downloads/CV/job-finder/agent
  python3 verify_real_applications.py                 # all time
  python3 verify_real_applications.py --days 7        # last 7 days only
  python3 verify_real_applications.py --days 1        # last 24h (did 24/7 runs work?)

Needs GMAIL_USER + GMAIL_APP_PASSWORD in agent/.env (never printed).
"""
import os
import sys
import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta

# ---- load .env (names only; values never printed) ----
for _path in ('.env', 'agent/.env'):
    if os.path.exists(_path):
        for line in open(_path):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

USER = os.environ.get('GMAIL_USER', '')
PW = os.environ.get('GMAIL_APP_PASSWORD', '')
if not USER or not PW:
    print("❌ GMAIL_USER / GMAIL_APP_PASSWORD not set in agent/.env — cannot verify.")
    sys.exit(1)

# --- args ---
days = 0
if '--days' in sys.argv:
    try:
        days = int(sys.argv[sys.argv.index('--days') + 1])
    except Exception:
        days = 0
cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days else None


def _dec(s):
    if not s:
        return ''
    return ''.join(
        t.decode(e or 'utf-8', 'ignore') if isinstance(t, bytes) else t
        for t, e in decode_header(s)
    )


# (label, IMAP search, subject/body markers that mean a REAL confirmation)
SOURCES = [
    ('Dice', '(FROM "applyonline@dice.com")',
     ('application for', 'sent', 'submitted', 'received')),
    ('Indeed', '(FROM "indeed.com")',
     ('application submitted', 'you applied', 'application was submitted',
      'has been submitted', 'application sent')),
    ('LinkedIn', '(FROM "jobs-noreply@linkedin.com")',
     ('your application was sent', 'application was sent', 'you applied')),
    ('Greenhouse/ATS', '(OR SUBJECT "thank you for applying" SUBJECT "application received")',
     ('thank you for applying', 'application received', 'we received your application',
      'successfully submitted')),
]


def main():
    M = imaplib.IMAP4_SSL('imap.gmail.com')
    M.login(USER, PW)
    # Search ALL mail, not just inbox — Gmail filters/labels may move confirmation
    # emails out of the inbox. '[Gmail]/All Mail' covers inbox + archived + labeled.
    try:
        M.select('"[Gmail]/All Mail"')
    except Exception:
        M.select('inbox')

    print(f"\n📬 REAL application confirmations in Gmail"
          + (f" (last {days} day(s))" if days else " (all time)") + ":\n")
    grand = 0
    per = {}
    # Build an IMAP server-side date filter (fast — avoids scanning All Mail client-side).
    since_imap = ""
    if days:
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        since_date = (_dt.now(_tz.utc) - _td(days=days)).strftime("%d-%b-%Y")
        since_imap = f'(SINCE "{since_date}")'
    for label, query, markers in SOURCES:
        try:
            full_query = f'{since_imap} {query}'.strip() if since_imap else query
            typ, data = M.search(None, full_query)
            ids = data[0].split() if data and data[0] else []
        except Exception as e:
            print(f"  {label:16s}: search error {str(e)[:40]}")
            continue
        count = 0
        samples = []
        # scan the matched set (SINCE already narrowed it server-side)
        for i in ids[-300:]:
            try:
                typ, md = M.fetch(i, '(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE)])')
                m = email.message_from_string(md[0][1].decode('utf-8', 'ignore'))
            except Exception:
                continue
            subj = _dec(m.get('Subject')) or ''
            if any(mk in subj.lower() for mk in markers):
                count += 1
                if len(samples) < 3:
                    samples.append(subj[:60])
        per[label] = count
        grand += count
        print(f"  {label:16s}: {count}")
        for s in samples:
            print(f"      • {s}")

    M.logout()
    print("  " + "-" * 30)
    print(f"  {'TOTAL REAL':16s}: {grand}")
    print("\n  (This is ground truth from employer/platform emails — not the local")
    print("   dedup caches. Run with --days 1 after a 24/7 cycle to confirm fresh sends.)\n")


if __name__ == '__main__':
    main()
