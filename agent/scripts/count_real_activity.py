#!/usr/bin/env python3
"""
Count REAL job activity from Gmail — all-time, no guessing.
Reports exact counts of:
  - Dice confirmed submits  (FROM applyonline@dice.com)
  - Indeed confirmed submits (SUBJECT "Indeed Application")
  - Greenhouse/Lever/Workday confirmations (common ATS confirmation senders)
  - Recruiter replies / interview signals
This reads the actual inbox — the only source of truth for what truly happened.
"""
import os, imaplib, email, re
from email.header import decode_header

user = os.environ.get("GMAIL_USER", "bobrikh75@gmail.com")
pw = os.environ.get("GMAIL_APP_PASSWORD", "")
if not pw:
    print("no gmail creds"); raise SystemExit

M = imaplib.IMAP4_SSL("imap.gmail.com")
M.login(user, pw)
M.select('"[Gmail]/All Mail"')  # search everything, incl. archived/labeled

def count(crit, label):
    try:
        typ, data = M.search(None, crit)
        n = len(data[0].split()) if data and data[0] else 0
        print(f"  {label:45}: {n}")
        return n
    except Exception as e:
        print(f"  {label:45}: ERR {str(e)[:40]}")
        return 0

print("=== REAL CONFIRMED SUBMISSIONS (platform said 'application sent/received') ===")
dice = count('(FROM "applyonline@dice.com")', "Dice 'Application sent' confirmations")
ind  = count('(SUBJECT "Indeed Application")', "Indeed 'Application' confirmations")
ind2 = count('(SUBJECT "application submitted")', "Generic 'application submitted'")
gh   = count('(FROM "greenhouse.io")', "Greenhouse confirmations")
gh2  = count('(FROM "notifications@greenhouse.io")', "Greenhouse notifications")
lever= count('(FROM "lever.co")', "Lever confirmations")
wd   = count('(FROM "myworkday.com")', "Workday confirmations")
recd = count('(SUBJECT "application received")', "'Application received' (any ATS)")
thx  = count('(SUBJECT "thank you for applying")', "'Thank you for applying'")

print("\n=== RECRUITER / INTERVIEW SIGNALS (real human responses) ===")
intv = count('(SUBJECT "interview")', "Subject contains 'interview'")
sched= count('(SUBJECT "schedule")', "Subject contains 'schedule'")
call = count('(BODY "available for a call")', "Body: 'available for a call'")
rtr  = count('(SUBJECT "right to represent")', "RTR requests (C2C submit)")
subm = count('(BODY "submit your profile")', "Body: 'submit your profile'")

print("\n=== SUMMARY ===")
confirmed = dice + ind + gh + gh2 + lever + wd
print(f"  Platform-confirmed submissions (approx, de-dup not applied): {confirmed}")
print(f"  Interview/schedule-signal emails: {intv + sched}")
print(f"  RTR (C2C represent) requests: {rtr}")
print("  NOTE: counts are raw email matches (may include threads/duplicates);")
print("        they prove REAL activity vs the bot's recorded numbers.")
M.logout()
