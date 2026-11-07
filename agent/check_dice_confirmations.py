#!/usr/bin/env python3
"""Confirm REAL Dice submits via Gmail. Dice sends 'Application for {TITLE} at
{COMPANY} sent' from applyonline@dice.com after a successful apply. We record the
confirmed titles so the bot skips them (like the Indeed email confirmer), and so we
can VERIFY a submit actually went through (Bobur: confirm from email, /cv pattern).

Usage:
  python3 check_dice_confirmations.py            # list + record all Dice confirmations
  python3 check_dice_confirmations.py --since-min 15   # only ones in the last N minutes
  python3 check_dice_confirmations.py --days 3         # reconcile the last N days (default 2)
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

import re

DAYS = 2
if '--days' in sys.argv:
    try:
        DAYS = int(sys.argv[sys.argv.index('--days') + 1])
    except Exception:
        pass


def norm(t):
    t = (t or '').lower()
    t = re.sub(r'\(.*?\)', ' ', t)
    t = re.sub(r'\b(sr|senior|jr|junior|lead|staff|principal|remote|w2|c2c|contract|us|usa)\b', ' ', t)
    return ' '.join(re.sub(r'[^a-z0-9 ]', ' ', t).split())


def jload(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default


def jsave(path, obj):
    os.makedirs('data', exist_ok=True)
    json.dump(obj, open(path, 'w'), indent=0)


M = imaplib.IMAP4_SSL('imap.gmail.com'); M.login(user, pw); M.select('inbox')
since = (datetime.now(timezone.utc) - timedelta(days=max(DAYS, 1))).strftime('%d-%b-%Y')
typ, data = M.search(None, f'(FROM "applyonline@dice.com" SINCE {since})')
ids = data[0].split()
print(f"Found {len(ids)} Dice confirmation emails in last {DAYS}d from applyonline@dice.com")
confs = []   # (subject_clean, title, company, datetime)
for i in ids:
    typ, md = M.fetch(i, '(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE)])')
    m = email.message_from_string(md[0][1].decode('utf-8', 'ignore'))
    subj = ' '.join(dec(m.get('Subject')).split())
    t = subj
    if t.lower().startswith('application for'):
        t = t[len('Application for'):].strip()
    if t.lower().endswith(' sent'):
        t = t[:-5].strip()
    if ' at ' in t:
        title, company = t.rsplit(' at ', 1)
    else:
        title, company = t, ''
    try:
        dt = parsedate_to_datetime(m.get('Date'))
    except Exception:
        dt = None
    confs.append((subj, title.strip(), company.strip(), dt))
M.logout()

# 1) legacy title list (kept for compatibility with other tools)
CONF = 'data/dice_email_confirmed_titles.json'
existing = set(jload(CONF, []))
before = len(existing)
existing.update(c[1] for c in confs if c[1])
jsave(CONF, sorted(existing))
print(f"Recorded {len(existing)} Dice email-confirmed titles ({len(existing) - before} new)")

# 2) RECONCILE with the bot's attempts: an email = Dice really received the application.
attempts = jload('data/dice_attempts.json', [])
applied_ids = jload('data/dice_applied_ids.json', {})
applied_titles = jload('data/dice_applied.json', {})
failed = jload('data/dice_failed_ids.json', {})
dead = jload('data/dice_dead_ids.json', {})
reasons = jload('data/dice_failed_reasons.json', {})
if not isinstance(applied_ids, dict): applied_ids = {str(x): time.time() for x in applied_ids}
if not isinstance(applied_titles, dict): applied_titles = {str(x): time.time() for x in applied_titles}
if not isinstance(failed, dict): failed = {}
if not isinstance(dead, dict): dead = {}
used = set()
fixed = 0
now = time.time()
for a in attempts:
    if a.get('result') == 'email_confirmed':
        continue
    nt = norm(a.get('title'))
    if not nt:
        continue
    comp = (a.get('company') or '').lower().split()
    for k, (subj, title, company, dt) in enumerate(confs):
        if k in used or norm(title) != nt:
            continue
        if comp and company and comp[0] not in company.lower() and company.lower().split()[0] not in (a.get('company') or '').lower():
            continue
        if dt and abs(dt.timestamp() - a.get('ts', 0)) > 3 * 3600:
            continue   # email must come within 3h of the attempt
        used.add(k)
        was = a.get('result')
        a['result'] = 'email_confirmed'
        jid = a.get('jid')
        if jid:
            applied_ids[jid] = now
            failed.pop(jid, None); dead.pop(jid, None); reasons.pop(jid, None)
        if a.get('company') or nt:
            applied_titles[f"{(a.get('company') or '').lower().strip()}|{nt}"] = now
        if was != 'submitted':
            fixed += 1
        break
jsave('data/dice_attempts.json', attempts)
jsave('data/dice_applied_ids.json', applied_ids)
jsave('data/dice_applied.json', applied_titles)
jsave('data/dice_failed_ids.json', failed)
jsave('data/dice_dead_ids.json', dead)
jsave('data/dice_failed_reasons.json', reasons)
print(f"Reconciled: {len(used)} email(s) matched bot attempts; {fixed} were logged as failed/incomplete "
      f"but Dice DID receive them -> moved to applied (failed/dead cleared)")

# 3) TRUTHFUL daily counters from Gmail (all confirmation emails by date, not bot guesses)
stats = jload('data/dice_stats.json', {})
per_day = {}
for subj, title, company, dt in confs:
    if dt:
        per_day[dt.astimezone().strftime('%Y-%m-%d')] = per_day.get(dt.astimezone().strftime('%Y-%m-%d'), 0) + 1
for day, n in per_day.items():
    d = stats.setdefault(day, {'attempted': 0, 'signal_submitted': 0, 'email_confirmed': 0})
    d['email_confirmed'] = max(d.get('email_confirmed', 0), n)
jsave('data/dice_stats.json', stats)
for day in sorted(stats)[-5:]:
    d = stats[day]
    print(f"  {day}: attempted={d['attempted']} page-signal={d['signal_submitted']} EMAIL-CONFIRMED={d['email_confirmed']}")

if cutoff:
    recent = [c[0] for c in confs if c[3] and c[3] >= cutoff]
    print(f"\n{len(recent)} confirmation(s) in the last {since_min} min:")
    for s_ in recent:
        print("  ✅", s_[:70])
