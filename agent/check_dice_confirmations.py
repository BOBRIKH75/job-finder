#!/usr/bin/env python3
"""Confirm REAL Dice submits via Gmail. Dice sends 'Application for {TITLE} at
{COMPANY} sent' from applyonline@dice.com after a successful apply. We record the
confirmed titles so the bot skips them (like the Indeed email confirmer), and so we
can VERIFY a submit actually went through (Bobur: confirm from email, /cv pattern).

Usage:
  python3 check_dice_confirmations.py            # list + record all Dice confirmations
  python3 check_dice_confirmations.py --since-min 15   # only ones in the last N minutes
"""
import os, imaplib, email, json, sys, time
from email.header import decode_header
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta

if os.path.exists('.env'):
    for line in open('.env'):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

user = os.environ.get('GMAIL_USER', '')
pw = os.environ.get('GMAIL_APP_PASSWORD', '')
if not user or not pw:
    print("no gmail creds"); raise SystemExit


def dec(s):
    if not s:
        return ''
    return ''.join(t.decode(e or 'utf-8', 'ignore') if isinstance(t, bytes) else t
                   for t, e in decode_header(s))


since_min = 0
if '--since-min' in sys.argv:
    try:
        since_min = int(sys.argv[sys.argv.index('--since-min') + 1])
    except Exception:
        since_min = 0
cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_min) if since_min else None

M = imaplib.IMAP4_SSL('imap.gmail.com'); M.login(user, pw); M.select('inbox')
# Dice confirmation: FROM applyonline@dice.com, SUBJECT "Application for ... sent"
typ, data = M.search(None, '(FROM "applyonline@dice.com")')
ids = data[0].split()
print(f"Found {len(ids)} Dice confirmation emails from applyonline@dice.com")
titles = []
recent = []
for i in ids[-60:]:
    typ, md = M.fetch(i, '(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE)])')
    m = email.message_from_string(md[0][1].decode('utf-8', 'ignore'))
    subj = dec(m.get('Subject'))
    # "Application for <TITLE> at <COMPANY> sent"
    t = subj
    if t.lower().startswith('application for'):
        t = t[len('Application for'):].strip()
    t = t[:-4].strip() if t.lower().endswith('sent') else t
    title_only = t.split(' at ')[0].strip() if ' at ' in t else t
    if title_only:
        titles.append(title_only)
    # recency check
    try:
        dt = parsedate_to_datetime(m.get('Date'))
        if cutoff and dt and dt >= cutoff:
            recent.append(subj)
    except Exception:
        pass
M.logout()

CONF = 'data/dice_email_confirmed_titles.json'
existing = set()
try:
    existing = set(json.load(open(CONF)))
except Exception:
    pass
before = len(existing)
existing.update(titles)
os.makedirs('data', exist_ok=True)
json.dump(sorted(existing), open(CONF, 'w'))
print(f"Recorded {len(existing)} Dice email-confirmed titles ({len(existing) - before} new)")
for t in sorted(existing)[:30]:
    print("  •", t[:70])
if since_min:
    print(f"\n{len(recent)} confirmation(s) in the last {since_min} min:")
    for s in recent:
        print("  ✅", s[:70])
