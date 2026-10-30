#!/usr/bin/env python3
"""Deep-read REAL recruiter replies and extract the useful info (roles, rates,
requirements, interview/RTR requests, recurring feedback). "Learn deeply" from the
inbox so Bob can act on the real leads and so the agent learns what recruiters say.

Reads bobrikh75@gmail.com (the user's OWN job-search inbox). Filters OUT:
  - emails Bob sent himself (his own hotlist blasts)
  - job-alert / noreply / platform notifications
  - bounces (postmaster/mailer-daemon)
Keeps only REAL humans who wrote TO Bob, and classifies + extracts each.

Writes: agent/data/recruiter_replies_digest.json  (structured, for the agent to learn)
Prints: a human-readable digest of the hottest leads.

Run: cd ~/Downloads/CV/job-finder/agent && python3 scripts/read_recruiter_replies.py [--days 30]
"""
import os
import re
import sys
import json
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timezone, timedelta

# ---- load .env ----
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

days = 30
if "--days" in sys.argv:
    try:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    except Exception:
        days = 30
since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")

NOISE = ("noreply", "no-reply", "jobs-noreply", "donotreply", "notification",
         "alert", "mailer-daemon", "postmaster", "indeed.com", "ziprecruiter",
         "linkedin.com", "glassdoor", "onboarding@resend", "crosschq", "micro1.ai")


def _dec(s):
    if not s:
        return ""
    return "".join(t.decode(e or "utf-8", "replace") if isinstance(t, bytes) else t
                   for t, e in decode_header(s))


def _body(msg):
    """Plain-text body (first text/plain part), truncated."""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    return part.get_payload(decode=True).decode("utf-8", "replace")
            # fall back to html stripped
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    html = part.get_payload(decode=True).decode("utf-8", "replace")
                    return re.sub(r"<[^>]+>", " ", html)
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode("utf-8", "replace")
    except Exception:
        pass
    return ""


# ---- extractors (the "useful info") ----
def extract_rate(text):
    m = re.search(r"\$?\s?(\d{2,3})\s?[-to/]{1,3}\s?\$?\s?(\d{2,3})\s?(?:/?\s?hr|/hour|per hour|hourly)",
                  text, re.I)
    if m:
        return f"${m.group(1)}-{m.group(2)}/hr"
    m = re.search(r"\$?\s?(\d{2,3})\s?(?:/?\s?hr|/hour|per hour|hourly|on c2c|c2c)", text, re.I)
    return f"${m.group(1)}/hr" if m else ""


def extract_location(text):
    m = re.search(r"\b(remote|hybrid|onsite|on-site|100%\s*remote)\b", text, re.I)
    loc = re.search(r"\b(?:location|based in|located in)[:\s]+([A-Za-z ,]{3,30})", text, re.I)
    parts = []
    if m:
        parts.append(m.group(1))
    if loc:
        parts.append(loc.group(1).strip())
    return " / ".join(parts)


def extract_role(text, subject):
    m = re.search(r"\b((?:senior |sr\.? |lead )?(?:java|spring|backend|full\s?stack|"
                  r"software)\s[\w /]{2,40}?(?:developer|engineer|architect))\b", subject + " " + text, re.I)
    return m.group(1).strip() if m else ""


def classify(subject, body):
    s = (subject + " " + body).lower()
    if any(k in s for k in ("right to represent", "rtr", "sign the rtr", "e-sign")):
        return "RTR_REQUEST"      # recruiter wants to represent you — HOT
    if any(k in s for k in ("schedule", "interview", "set up a call", "availability for a call",
                            "are you available", "book a time", "calendly")):
        return "INTERVIEW/CALL"   # HOT
    if any(k in s for k in ("rate", "what is your rate", "expected rate", "your bill rate")):
        return "RATE_QUESTION"
    if any(k in s for k in ("us citizen", "citizenship", "need usc", "only citizens",
                            "security clearance", "clearance required", "w2 only", "no c2c")):
        return "REQUIREMENT_BLOCKER"  # tells us what's filtering you out — LEARN
    if any(k in s for k in ("not a fit", "moved forward", "position has been filled",
                            "no longer", "unfortunately")):
        return "REJECTION"
    if any(k in s for k in ("new requirement", "we have an opening", "role for you",
                            "opportunity", "position available", "req ")):
        return "NEW_ROLE"
    return "OTHER"


def main():
    M = imaplib.IMAP4_SSL("imap.gmail.com")
    M.login(USER, PW)
    M.select('"[Gmail]/All Mail"')

    # Pull candidate replies: things that look like recruiter engagement, recent only.
    seen_ids = set()
    collected = []
    for crit in ('(SUBJECT "interview")', '(SUBJECT "right to represent")',
                 '(SUBJECT "opportunity")', '(SUBJECT "requirement")',
                 '(SUBJECT "your resume")', '(SUBJECT "java")', '(BODY "your rate")'):
        typ, data = M.search(None, f'(SINCE "{since}")', crit)
        ids = data[0].split() if data and data[0] else []
        for i in ids[-60:]:
            if i in seen_ids:
                continue
            seen_ids.add(i)
            typ, md = M.fetch(i, "(RFC822)")
            if not md or not md[0]:
                continue
            msg = email.message_from_bytes(md[0][1])
            frm = _dec(msg.get("From", "")).lower()
            addr = frm.split("<")[-1].strip("> ").strip()
            if USER in frm:                      # Bob's own sends
                continue
            if any(n in frm for n in NOISE):     # noise / bounces / platforms
                continue
            subject = _dec(msg.get("Subject", ""))
            date = _dec(msg.get("Date", ""))
            body = _body(msg)[:2500]
            kind = classify(subject, body)
            collected.append({
                "from": addr, "subject": subject[:90], "date": date[:31],
                "kind": kind,
                "role": extract_role(body, subject),
                "rate": extract_rate(body),
                "location": extract_location(body),
                "snippet": re.sub(r"\s+", " ", body)[:240],
            })
    M.logout()

    # Save structured digest (dedup by from+subject)
    uniq = {}
    for c in collected:
        uniq[(c["from"], c["subject"])] = c
    rows = list(uniq.values())
    out = "data/recruiter_replies_digest.json" if os.path.isdir("data") else \
          "agent/data/recruiter_replies_digest.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(rows, open(out, "w"), indent=2)

    # ---- human digest ----
    from collections import Counter
    kinds = Counter(c["kind"] for c in rows)
    print(f"\n📬 Recruiter replies — last {days} days: {len(rows)} real human emails\n")
    print("By type:")
    for k, n in kinds.most_common():
        print(f"  {n:3}  {k}")

    PRIORITY = ["RTR_REQUEST", "INTERVIEW/CALL", "NEW_ROLE", "RATE_QUESTION",
                "REQUIREMENT_BLOCKER", "REJECTION", "OTHER"]
    for kind in PRIORITY:
        hot = [c for c in rows if c["kind"] == kind]
        if not hot:
            continue
        label = {"RTR_REQUEST": "🔥 RIGHT-TO-REPRESENT (recruiter wants to represent you — REPLY!)",
                 "INTERVIEW/CALL": "🔥 INTERVIEW / CALL REQUESTS (REPLY!)",
                 "NEW_ROLE": "💼 NEW ROLES OFFERED",
                 "RATE_QUESTION": "💲 ASKED YOUR RATE (reply to keep it moving)",
                 "REQUIREMENT_BLOCKER": "⚠️ REQUIREMENT BLOCKERS (what's filtering you out — LEARN)",
                 "REJECTION": "❌ REJECTIONS",
                 "OTHER": "• OTHER"}[kind]
        print(f"\n{label}")
        for c in hot[:12]:
            extra = " ".join(x for x in (c["role"], c["rate"], c["location"]) if x)
            print(f"   • {c['from']:<34} {('['+extra+']') if extra else ''}")
            print(f"     {c['subject']}")
            if kind in ("REQUIREMENT_BLOCKER", "NEW_ROLE", "RATE_QUESTION"):
                print(f"     ↳ {c['snippet'][:150]}")
            # RATE QUESTION → generate the market-value strategic reply (anchor high).
            if kind == "RATE_QUESTION":
                try:
                    try:
                        from rate_strategy import build_rate_reply
                    except Exception:
                        from scripts.rate_strategy import build_rate_reply
                    name = c["from"].split("@")[0].replace(".", " ").title()
                    _subj, _reply_body, r = build_rate_reply(name, c["role"], c["snippet"])
                    print(f"     💡 MARKET TARGET: ${r['target']}/hr  (quote ${r['low']}-{r['high']}/hr)"
                          f"  factors: {', '.join(r['factors']) or 'base'}")
                    print(f"     💬 suggested reply saved → see rate_reply below")
                    c["suggested_rate_reply"] = _reply_body
                    c["rate_target"] = r["target"]
                    c["rate_range"] = [r["low"], r["high"]]
                except Exception as _e:
                    pass

    # ---- learnings summary ----
    blockers = [c for c in rows if c["kind"] == "REQUIREMENT_BLOCKER"]
    if blockers:
        print("\n🧠 LEARNED (recurring requirement blockers):")
        txt = " ".join(c["snippet"].lower() for c in blockers)
        for pat, msg in [("citizen", "Some roles need US CITIZEN (you're GC) — can't fix, skip faster"),
                         ("clearance", "Some need SECURITY CLEARANCE — skip these"),
                         ("w2 only", "Some are W2-only (not C2C) — filter out"),
                         ("no c2c", "Some explicitly NO C2C — filter out")]:
            n = txt.count(pat)
            if n:
                print(f"   • {msg}  (seen {n}x)")

    print(f"\n💾 Saved structured digest → {out}")
    print("   Reply to the 🔥 ones by hand — those are your real opportunities.")


if __name__ == "__main__":
    main()
