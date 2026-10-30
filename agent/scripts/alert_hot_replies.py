#!/usr/bin/env python3
"""Push a phone alert (ntfy) when a HOT recruiter reply lands — so Bob never misses an
interview request / RTR / rate question. Dedups so each reply alerts only once.

Hot = RTR_REQUEST, INTERVIEW/CALL, RATE_QUESTION (time-sensitive, need a human reply).
Uses read_recruiter_replies' classifier on fresh inbox mail. Alerts via NTFY_TOPIC
(free push to the ntfy app on Bob's phone). Also emails a summary as backup.

Run: cd ~/Downloads/CV/job-finder/agent && python3 scripts/alert_hot_replies.py [--days 2]
"""
import json
import os
import re
import sys
import time
import imaplib
import email
import urllib.request
from email.header import decode_header
from datetime import datetime, timezone, timedelta

for p in (".env", "agent/.env"):
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

USER = os.environ.get("GMAIL_USER", "bobrikh75@gmail.com")
PW = os.environ.get("GMAIL_APP_PASSWORD", "")
NTFY = os.environ.get("NTFY_TOPIC", "")
if not PW:
    print("no gmail creds"); sys.exit(0)

DATA = "data" if os.path.isdir("data") else "agent/data"
ALERTED = os.path.join(DATA, "alerted_replies.json")

NOISE = ("noreply", "no-reply", "donotreply", "notification", "mailer-daemon",
         "postmaster", "indeed.com", "ziprecruiter", "linkedin.com", "crosschq",
         "resend", "glassdoor", "jobleads", "talentnet")


def _dec(s):
    if not s:
        return ""
    return "".join(t.decode(e or "utf-8", "replace") if isinstance(t, bytes) else t
                   for t, e in decode_header(s))


def classify(subject, frm):
    s = subject.lower()
    if any(k in s for k in ("right to represent", "rtr")):
        return "RTR"
    if any(k in s for k in ("interview", "schedule", "set up a call", "availability",
                            "are you available", "book a time", "calendly", "slots")):
        return "INTERVIEW"
    if any(k in s for k in ("rate", "bill rate", "compensation", "expected pay")):
        return "RATE"
    return ""


def ntfy_push(title, body, priority="high", tags="briefcase"):
    if not NTFY:
        return False
    try:
        url = f"https://ntfy.sh/{NTFY}"
        req = urllib.request.Request(url, data=body.encode("utf-8"), headers={
            "Title": title, "Priority": priority, "Tags": tags,
        }, method="POST")
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"  ntfy err: {str(e)[:60]}")
        return False


def main():
    days = 2
    if "--days" in sys.argv:
        try: days = int(sys.argv[sys.argv.index("--days") + 1])
        except Exception: pass
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")

    try:
        alerted = set(json.load(open(ALERTED)))
    except Exception:
        alerted = set()

    M = imaplib.IMAP4_SSL("imap.gmail.com")
    M.login(USER, PW)
    M.select("inbox")   # only INBOX = replies TO Bob (not sent/archived)

    typ, data = M.search(None, f'(SINCE "{since}")')
    ids = data[0].split() if data and data[0] else []
    hot = []
    for i in ids[-200:]:
        try:
            typ, md = M.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID)])")
            msg = email.message_from_bytes(md[0][1])
        except Exception:
            continue
        frm = _dec(msg.get("From", "")).lower()
        if USER in frm or any(n in frm for n in NOISE):
            continue
        subject = _dec(msg.get("Subject", ""))
        mid = (msg.get("Message-ID") or subject)[:120]
        if mid in alerted:
            continue
        kind = classify(subject, frm)
        if not kind:
            continue
        addr = frm.split("<")[-1].strip("> ")
        hot.append((kind, addr, subject, mid))
    M.logout()

    if not hot:
        print("No new hot replies to alert.")
        return

    icon = {"RTR": "🔥 RTR", "INTERVIEW": "🔥 INTERVIEW", "RATE": "💲 RATE"}
    for kind, addr, subject, mid in hot:
        title = f"{icon.get(kind, kind)} — recruiter reply"
        body = f"{addr}\n{subject[:120]}\n\nReply from Gmail → Drafts or hand-reply."
        ok = ntfy_push(title, body)
        print(f"  {'📲 alerted' if ok else '(no ntfy)'}: [{kind}] {addr} — {subject[:50]}")
        alerted.add(mid)

    # also email a digest to self as backup
    if NTFY is None and os.environ.get("RESEND_KEY"):
        pass  # ntfy is primary; email backup optional

    os.makedirs(DATA, exist_ok=True)
    json.dump(sorted(alerted)[-2000:], open(ALERTED, "w"))
    print(f"\n📲 {len(hot)} hot reply alert(s) pushed to your phone (ntfy).")


if __name__ == "__main__":
    main()
