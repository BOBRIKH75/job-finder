#!/usr/bin/env python3
"""Draft ready-to-send replies to Bob's HOT recruiter leads — straight into Gmail Drafts.

The warmest opportunities (Right-to-Represent, interview requests, new roles, rate
questions) are already in the inbox. Converting them to interviews just needs a fast,
professional reply. This reads the hot leads, writes a tailored reply for each, and
saves it as a Gmail DRAFT (via IMAP APPEND to [Gmail]/Drafts) so Bob reviews + hits Send.

NOTHING is auto-sent — drafts only. Bob stays in control of wording + send.

Reads the digest from read_recruiter_replies.py (run that first, or this runs it).

Usage:
  cd ~/Downloads/CV/job-finder/agent && python3 scripts/draft_hot_lead_replies.py [--days 45]
"""
import os
import re
import sys
import json
import imaplib
import time
from datetime import datetime
from email.mime.text import MIMEText

for p in (".env", "agent/.env"):
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

USER = os.environ.get("GMAIL_USER", "bobrikh75@gmail.com")
PW = os.environ.get("GMAIL_APP_PASSWORD", "")
if not PW:
    print("❌ GMAIL_APP_PASSWORD not set"); sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from rate_strategy import build_rate_reply, compute_rate
except Exception:
    build_rate_reply = compute_rate = None

RESUME = "https://drive.google.com/drive/folders/1sJRyHCTC2Xend6VWn6hM07VufWQdw_qV"
LINKEDIN = "https://www.linkedin.com/in/bobrikh75/"
BOOK = "https://calendar.google.com/calendar/u/0/appointments/AcZssZ22KPDPginBf34kMvb6wAFQUEHtG5sJ3PF_1k8="
SIG = (f"\n\nBest regards,\nBob Rikh\nSenior Java Back-End Developer\n"
       f"347-268-5917 | {USER}\nResume: {RESUME}\nLinkedIn: {LINKEDIN}\n"
       f"Book a call: {BOOK}\n")


def _first_name(addr, fallback=""):
    local = addr.split("@")[0]
    local = re.split(r"[._]", local)[0]
    return local.title() if local and local.isalpha() else fallback


def draft_for(lead):
    """Return (subject, body) tailored to the lead's kind."""
    kind = lead.get("kind", "OTHER")
    addr = lead.get("from", "")
    name = _first_name(addr)
    greet = f"Hi {name}," if name else "Hi,"
    role = lead.get("role") or "the role"
    subj_in = lead.get("subject", "")
    re_subj = subj_in if subj_in.lower().startswith("re:") else f"Re: {subj_in}"

    if kind == "RTR_REQUEST":
        body = (
            f"{greet}\n\n"
            f"Yes — I'm interested and happy to move forward on {role}. You have my "
            f"authorization to represent me for this position with the client.\n\n"
            f"For the submission, my details:\n"
            f"  Full name: Bob Rikh\n"
            f"  Location: Parker, CO 80314 (open to remote; hybrid/onsite in CO works)\n"
            f"  Work authorization: Green Card holder — no sponsorship needed\n"
            f"  Availability: Immediately (2 weeks' notice if needed)\n"
            f"  Engagement: C2C preferred\n\n"
            f"Please send the RTR and any final rate/details and I'll confirm right away. "
            f"What rate has the client approved for this role?\n"
            + SIG)
        return re_subj, body

    if kind == "INTERVIEW/CALL":
        body = (
            f"{greet}\n\n"
            f"Thank you — yes, I'm very interested in {role} and available to interview.\n\n"
            f"I'm open most weekdays; a few slots that work well for me (MT):\n"
            f"  - Today/tomorrow 10:00 AM - 12:00 PM\n"
            f"  - Afternoons 2:00 - 5:00 PM\n"
            f"Share the client's preferred time and format (phone / video / F2F) and I'll "
            f"confirm. You can also grab a time directly here: {BOOK}\n\n"
            f"Quick confirm on logistics: is this remote, hybrid, or onsite, and is it C2C?\n"
            + SIG)
        return re_subj, body

    if kind == "NEW_ROLE":
        body = (
            f"{greet}\n\n"
            f"Thanks for reaching out about {role} — it looks like a strong fit for my "
            f"background (Java 17, Spring Boot, microservices, Kafka, Kubernetes, AWS, "
            f"10+ years).\n\n"
            f"I'm actively open to C2C contract work. A few quick questions so I can confirm fit:\n"
            f"  1. Remote, hybrid, or onsite?\n"
            f"  2. Direct client or vendor layer?\n"
            f"  3. Contract length + rate range approved?\n"
            f"  4. Scope — IC vs architecture/lead?\n\n"
            f"I'm a Green Card holder (no sponsorship), available immediately. Resume attached "
            f"below — happy to jump on a call.\n"
            + SIG)
        return re_subj, body

    if kind == "RATE_QUESTION" and build_rate_reply:
        s, b, r = build_rate_reply(name, role, lead.get("snippet", ""))
        return (s if s.lower().startswith("re:") else re_subj), b

    # OTHER / fallback — polite interested reply
    body = (
        f"{greet}\n\n"
        f"Thanks for reaching out regarding {role}. I'm a Senior Java Back-End Developer "
        f"(10+ yrs, Spring Boot / microservices / Kafka / Kubernetes / AWS), Green Card "
        f"holder, available immediately for C2C contract work (remote preferred, CO-based).\n\n"
        f"If this is a fit, I'd love to connect — what are the role details (remote/onsite, "
        f"length, rate)?\n"
        + SIG)
    return re_subj, body


def save_draft(imap, to_addr, subject, body):
    """APPEND an RFC822 message to the Gmail Drafts folder (not sent)."""
    msg = MIMEText(body, "plain")
    msg["From"] = f"Bob Rikh <{USER}>"
    msg["To"] = to_addr
    msg["Subject"] = subject
    raw = msg.as_bytes()
    try:
        imap.append('"[Gmail]/Drafts"', "", imaplib.Time2Internaldate(time.time()), raw)
        return True
    except Exception as e:
        print(f"    draft save failed: {str(e)[:60]}")
        return False


def main():
    days = 45
    if "--days" in sys.argv:
        try:
            days = int(sys.argv[sys.argv.index("--days") + 1])
        except Exception:
            days = 45

    # Load the digest (produce it if missing)
    digest_path = "data/recruiter_replies_digest.json" if os.path.isdir("data") \
        else "agent/data/recruiter_replies_digest.json"
    if not os.path.exists(digest_path):
        print("No digest yet — running read_recruiter_replies.py first...")
        os.system(f"python3 scripts/read_recruiter_replies.py --days {days} >/dev/null 2>&1")
    try:
        leads = json.load(open(digest_path))
    except Exception:
        print("❌ could not load digest"); sys.exit(1)

    HOT = {"RTR_REQUEST", "INTERVIEW/CALL", "NEW_ROLE", "RATE_QUESTION"}
    # Skip platform/noreply senders — only real recruiters
    hot_leads = [l for l in leads if l.get("kind") in HOT
                 and "@" in l.get("from", "")
                 and not any(n in l["from"] for n in
                             ("dice.com", "noreply", "no-reply", "talentnet", "jobleads",
                              "crosschq", "trakstar", "resend"))]

    if not hot_leads:
        print("No hot leads to draft right now. Run read_recruiter_replies.py to refresh.")
        return

    M = imaplib.IMAP4_SSL("imap.gmail.com")
    M.login(USER, PW)

    # De-dup by sender (one draft per recruiter — the most recent/hottest)
    by_sender = {}
    order = {"RTR_REQUEST": 0, "INTERVIEW/CALL": 1, "NEW_ROLE": 2, "RATE_QUESTION": 3}
    for l in sorted(hot_leads, key=lambda x: order.get(x["kind"], 9)):
        by_sender.setdefault(l["from"], l)

    made = 0
    print(f"\n✍️  Drafting replies for {len(by_sender)} hot recruiter leads "
          f"(saved to Gmail Drafts — NOTHING sent)\n")
    for addr, lead in by_sender.items():
        subject, body = draft_for(lead)
        if save_draft(M, addr, subject, body):
            made += 1
            tag = lead["kind"]
            print(f"  ✅ DRAFT → {addr:<34} [{tag}]  {subject[:50]}")
    M.logout()

    print(f"\n💾 {made} drafts saved in Gmail → open Gmail → Drafts → review → Send.")
    print("   Priority order: RTR first, then interview requests, then new roles.")
    print("   These are your warmest leads — a fast reply is what converts them.")


if __name__ == "__main__":
    main()
