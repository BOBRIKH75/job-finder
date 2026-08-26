#!/usr/bin/env python3
"""
Smart Reply Tracker — Detects recruiter reply TYPE and tracks interview pipeline.

Pipeline stages:
  CONTACTED → REPLIED → INTERESTED → INTERVIEW_SCHEDULED → INTERVIEW_DONE → OFFER

Reply classification (keyword-based, no AI needed):
  - INTERESTED: wants to discuss, asks for availability, "good fit", forward CV
  - INTERVIEW: schedule, interview, call, meet, zoom, teams link, calendar
  - REJECTION: not a match, position filled, moved forward with other, no longer available
  - INFO_REQUEST: rate?, availability?, visa?, location?, more details
  - AUTO_REPLY: out of office, automatic reply, OOO

Run daily via GitHub Actions or manually.
Cross-checks BOTH main contacted.json AND apollo_contacted.json.
"""
import imaplib
import email
import json
import os
import re
from datetime import datetime
from email.header import decode_header
from pathlib import Path

# ─── Config ───────────────────────────────────────────────────────────────────
GMAIL_USER = os.environ.get("GMAIL_USER", "bobrikh75@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

DATA_DIR = Path(__file__).parent.parent / "data"
PIPELINE_FILE = DATA_DIR / "interview_pipeline.json"
REPLY_LOG_FILE = DATA_DIR / "reply_log.json"

# All contacted files to cross-check
CONTACTED_FILES = [
    Path(__file__).parent.parent.parent / "contacted.json",  # main outreach
    DATA_DIR / "apollo_contacted.json",                       # apollo outreach
    DATA_DIR / "vendor_outreach_history.json",                # vendor outreach
]

# ─── Reply Classification Keywords ───────────────────────────────────────────
_INTERVIEW_KEYWORDS = [
    r"schedul", r"interview", r"call.*with", r"meet.*with",
    r"zoom\s*(link|meeting|call)", r"teams\s*(link|meeting|call)",
    r"webex", r"google\s*meet", r"phone\s*screen",
    r"let'?s\s*(talk|connect|chat|discuss)", r"set\s*up.*call",
    r"calendar\s*(link|invite)", r"pick\s*a\s*time",
    r"avail.*for.*call", r"book\s*a\s*time",
    r"what\s*time\s*works", r"when\s*are\s*you\s*(free|available)",
]

_INTERESTED_KEYWORDS = [
    r"good\s*fit", r"strong\s*match", r"great\s*candidate",
    r"forward.*cv", r"forward.*resume", r"submit.*profile",
    r"present.*to.*client", r"client.*interested",
    r"would\s*like\s*to\s*(discuss|talk|connect)",
    r"reach\s*out", r"touch\s*base", r"follow\s*up",
    r"opportunity", r"position.*open", r"role.*available",
    r"requirement.*match", r"perfect\s*for",
    r"share.*details", r"send.*job\s*description",
]

_REJECTION_KEYWORDS = [
    r"not\s*(a|the)\s*match", r"position\s*(has\s*been\s*)?filled",
    r"moved\s*forward\s*with\s*other", r"no\s*longer\s*(available|open)",
    r"not\s*hiring", r"unfortunately", r"regret\s*to\s*inform",
    r"does\s*not\s*(align|match|fit)", r"not\s*a\s*good\s*fit",
    r"thank.*but", r"won'?t\s*be\s*moving\s*forward",
    r"decided\s*to\s*(go|proceed)\s*with", r"not\s*suitable",
]

_INFO_REQUEST_KEYWORDS = [
    r"what.*rate", r"rate\s*expectation", r"hourly\s*rate",
    r"availability\s*\?", r"when.*start", r"notice\s*period",
    r"visa\s*status", r"work\s*authorization", r"sponsorship",
    r"location\s*\?", r"remote\s*\?", r"on-?site",
    r"years?\s*of\s*experience", r"can\s*you\s*(share|send|provide)",
    r"more\s*details", r"updated?\s*resume", r"latest\s*cv",
]

_AUTO_REPLY_KEYWORDS = [
    r"out\s*of\s*(the\s*)?office", r"automatic\s*reply",
    r"auto-?reply", r"OOO", r"on\s*vacation", r"on\s*leave",
    r"limited\s*access\s*to\s*email", r"will\s*(respond|reply)\s*when",
    r"currently\s*away", r"not\s*available\s*until",
]

# Acknowledgment — recruiter confirms receipt (don't follow up, they're reviewing)
_ACKNOWLEDGMENT_KEYWORDS = [
    r"(thank|thanks)\s*(you)?\s*for\s*(your|the|sending|reaching)",
    r"(received|got)\s*(your)?\s*(resume|cv|profile|application)",
    r"will\s*(review|look|go\s*through|check)",
    r"(i'?ll|we'?ll)\s*(get\s*back|respond|follow\s*up|reach\s*out)",
    r"under\s*review", r"reviewing\s*(your|the)",
    r"keep\s*(you|your\s*resume)\s*(on\s*file|in\s*mind)",
    r"(noted|acknowledged)", r"added\s*to\s*(our|the)\s*(database|system|pool)",
    r"if\s*(something|a\s*position|anything)\s*(comes\s*up|opens|matches)",
]


def classify_reply(subject: str, body: str) -> str:
    """Classify a recruiter reply into a pipeline stage.
    
    Returns one of:
      INTERVIEW_SCHEDULED, INTERESTED, REJECTION, INFO_REQUEST, AUTO_REPLY, REPLIED
    """
    text = f"{subject} {body}".lower()

    # Check in priority order (most specific first)
    for pattern in _INTERVIEW_KEYWORDS:
        if re.search(pattern, text):
            return "INTERVIEW_SCHEDULED"

    for pattern in _AUTO_REPLY_KEYWORDS:
        if re.search(pattern, text):
            return "AUTO_REPLY"

    for pattern in _REJECTION_KEYWORDS:
        if re.search(pattern, text):
            return "REJECTION"

    for pattern in _INTERESTED_KEYWORDS:
        if re.search(pattern, text):
            return "INTERESTED"

    for pattern in _INFO_REQUEST_KEYWORDS:
        if re.search(pattern, text):
            return "INFO_REQUEST"

    for pattern in _ACKNOWLEDGMENT_KEYWORDS:
        if re.search(pattern, text):
            return "ACKNOWLEDGED"

    # Default: they replied but we can't classify
    return "REPLIED"


def load_all_contacted() -> dict:
    """Load all contacted records from ALL pipeline files.
    Returns: {email_hash: {email, company, job, ...}}
    """
    import hashlib
    merged = {}

    for filepath in CONTACTED_FILES:
        if not filepath.exists():
            continue
        try:
            data = json.loads(filepath.read_text())
            if isinstance(data, dict):
                merged.update(data)
            elif isinstance(data, list):
                for entry in data:
                    e = entry.get("email", "")
                    if e:
                        h = hashlib.md5(e.lower().encode()).hexdigest()[:12]
                        merged[h] = entry
        except Exception:
            pass

    return merged


def load_pipeline() -> dict:
    """Load the interview pipeline state."""
    if PIPELINE_FILE.exists():
        try:
            return json.loads(PIPELINE_FILE.read_text())
        except Exception:
            pass
    return {
        "contacts": {},  # email -> pipeline entry
        "stats": {
            "total_contacted": 0,
            "replied": 0,
            "interested": 0,
            "interview_scheduled": 0,
            "interview_done": 0,
            "offers": 0,
            "rejections": 0,
        },
        "last_updated": None,
    }


def save_pipeline(pipeline: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pipeline["last_updated"] = datetime.now().isoformat()
    PIPELINE_FILE.write_text(json.dumps(pipeline, indent=2))


def connect_imap() -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL("imap.gmail.com")
    conn.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    return conn


def decode_subject(msg) -> str:
    """Decode email subject header."""
    raw = msg.get("Subject", "")
    if not raw:
        return ""
    decoded_parts = decode_header(raw)
    parts = []
    for content, charset in decoded_parts:
        if isinstance(content, bytes):
            parts.append(content.decode(charset or "utf-8", errors="ignore"))
        else:
            parts.append(content)
    return " ".join(parts)


def get_body(msg) -> str:
    """Extract plain text body from email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    break
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
        except Exception:
            pass
    # Truncate for classification (first 2000 chars is enough)
    return body[:2000]


def find_replies(conn: imaplib.IMAP4_SSL, contacted: dict) -> list:
    """Search Gmail for replies from all contacted recruiters.
    
    Returns list of: {email, subject, body, date, classification, contact_info}
    """
    replies = []
    conn.select("INBOX")

    # Get emails we've sent to (to avoid false positives from random senders)
    contacted_emails = set()
    for info in contacted.values():
        e = info.get("email", "").lower()
        if e:
            contacted_emails.add(e)

    print(f"  Checking replies from {len(contacted_emails)} unique recruiters...")

    for recruiter_email in contacted_emails:
        try:
            _, data = conn.search(None, f'(FROM "{recruiter_email}")')
            msg_ids = data[0].split()
            if not msg_ids:
                continue

            # Get the most recent message from this sender
            _, msg_data = conn.fetch(msg_ids[-1], "(RFC822)")
            raw_msg = email.message_from_bytes(msg_data[0][1])

            subject = decode_subject(raw_msg)
            body = get_body(raw_msg)
            date_str = raw_msg.get("Date", "")

            classification = classify_reply(subject, body)

            replies.append({
                "email": recruiter_email,
                "subject": subject,
                "body_preview": body[:200],  # Don't store full body
                "date": date_str,
                "classification": classification,
            })

        except Exception as e:
            # Don't spam errors — just skip
            pass

    return replies


def update_contacted_files(replies: list):
    """Update ALL contacted files with reply status."""
    import hashlib

    for filepath in CONTACTED_FILES:
        if not filepath.exists():
            continue
        try:
            data = json.loads(filepath.read_text())
            if not isinstance(data, dict):
                continue

            updated = False
            for reply in replies:
                h = hashlib.md5(reply["email"].lower().encode()).hexdigest()[:12]
                if h in data and not data[h].get("replied"):
                    data[h]["replied"] = True
                    data[h]["replied_at"] = reply["date"]
                    data[h]["reply_type"] = reply["classification"]
                    updated = True

            if updated:
                filepath.write_text(json.dumps(data, indent=2))
        except Exception:
            pass


def main():
    print("=" * 60)
    print("🎯 SMART REPLY TRACKER — Interview Pipeline")
    print("=" * 60)
    print(f"   Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    if not GMAIL_APP_PASSWORD:
        print("❌ GMAIL_APP_PASSWORD not set — cannot check inbox")
        return

    # Load all contacted records
    contacted = load_all_contacted()
    if not contacted:
        print("⚠️  No contacted records found — nothing to check")
        return

    print(f"📋 Total contacts tracked: {len(contacted)}")

    # Connect to Gmail
    try:
        conn = connect_imap()
    except Exception as e:
        print(f"❌ Gmail IMAP connect failed: {e}")
        return

    # Find replies
    replies = find_replies(conn, contacted)
    conn.logout()

    if not replies:
        print("\n📭 No replies found this run")
        return

    # Load pipeline
    pipeline = load_pipeline()

    # Process replies
    new_replies = []
    for reply in replies:
        email_addr = reply["email"].lower()

        # Skip if already tracked in pipeline with same or higher stage
        existing = pipeline["contacts"].get(email_addr, {})
        existing_stage = existing.get("stage", "")

        # Stage priority (higher = further along)
        stage_priority = {
            "": 0, "CONTACTED": 1, "REPLIED": 2, "AUTO_REPLY": 2,
            "INFO_REQUEST": 3, "INTERESTED": 4, "REJECTION": 5,
            "INTERVIEW_SCHEDULED": 6, "INTERVIEW_DONE": 7, "OFFER": 8,
        }

        new_stage = reply["classification"]
        if stage_priority.get(new_stage, 0) <= stage_priority.get(existing_stage, 0):
            continue  # Don't downgrade

        # Update pipeline
        pipeline["contacts"][email_addr] = {
            "email": email_addr,
            "stage": new_stage,
            "subject": reply["subject"],
            "date": reply["date"],
            "body_preview": reply["body_preview"],
            "updated": datetime.now().isoformat(),
            # Carry forward info from contacted
            "company": existing.get("company", ""),
            "name": existing.get("name", ""),
        }

        # Find company/name from contacted records
        import hashlib
        h = hashlib.md5(email_addr.encode()).hexdigest()[:12]
        if h in contacted:
            info = contacted[h]
            pipeline["contacts"][email_addr]["company"] = info.get("company", "")
            pipeline["contacts"][email_addr]["name"] = info.get("name", "")

        new_replies.append(reply)

    # Update stats
    stages = [c.get("stage", "") for c in pipeline["contacts"].values()]
    pipeline["stats"] = {
        "total_contacted": len(contacted),
        "replied": sum(1 for s in stages if s in ("REPLIED", "INFO_REQUEST", "INTERESTED", "INTERVIEW_SCHEDULED")),
        "interested": sum(1 for s in stages if s == "INTERESTED"),
        "interview_scheduled": sum(1 for s in stages if s == "INTERVIEW_SCHEDULED"),
        "interview_done": sum(1 for s in stages if s == "INTERVIEW_DONE"),
        "offers": sum(1 for s in stages if s == "OFFER"),
        "rejections": sum(1 for s in stages if s == "REJECTION"),
        "auto_replies": sum(1 for s in stages if s == "AUTO_REPLY"),
    }

    # Save pipeline
    save_pipeline(pipeline)

    # Update contacted files
    update_contacted_files(new_replies)

    # Save reply log
    reply_log = []
    if REPLY_LOG_FILE.exists():
        try:
            reply_log = json.loads(REPLY_LOG_FILE.read_text())
        except Exception:
            pass
    for r in new_replies:
        reply_log.append({
            "email": r["email"],
            "classification": r["classification"],
            "subject": r["subject"],
            "date": r["date"],
            "detected_at": datetime.now().isoformat(),
        })
    REPLY_LOG_FILE.write_text(json.dumps(reply_log, indent=2))

    # Print results
    print(f"\n📬 New replies detected: {len(new_replies)}")
    if new_replies:
        print()
        for r in new_replies:
            emoji = {
                "INTERVIEW_SCHEDULED": "🎯",
                "INTERESTED": "🟢",
                "INFO_REQUEST": "📋",
                "REPLIED": "💬",
                "REJECTION": "🔴",
                "AUTO_REPLY": "🔄",
            }.get(r["classification"], "💬")
            print(f"  {emoji} [{r['classification']}] {r['email']}")
            print(f"     Subject: {r['subject'][:60]}")
            print()

    # Pipeline summary
    s = pipeline["stats"]
    print(f"\n📊 PIPELINE STATUS:")
    print(f"   ┌─────────────────────────────────────────┐")
    print(f"   │ Total Contacted:     {s['total_contacted']:>5}              │")
    print(f"   │ Replied (any):       {s['replied']:>5}              │")
    print(f"   │ 🟢 Interested:       {s['interested']:>5}              │")
    print(f"   │ 🎯 Interview Sched:  {s['interview_scheduled']:>5}              │")
    print(f"   │ ✅ Interview Done:   {s['interview_done']:>5}              │")
    print(f"   │ 🏆 Offers:           {s['offers']:>5}              │")
    print(f"   │ 🔴 Rejections:       {s['rejections']:>5}              │")
    print(f"   │ 🔄 Auto-replies:     {s['auto_replies']:>5}              │")
    print(f"   └─────────────────────────────────────────┘")

    # Action items
    interviews = [c for c in pipeline["contacts"].values() if c.get("stage") == "INTERVIEW_SCHEDULED"]
    if interviews:
        print(f"\n⚡ ACTION REQUIRED — {len(interviews)} interview(s) to confirm:")
        for c in interviews:
            print(f"   → {c.get('name', c['email'])} @ {c.get('company', '?')}")
            print(f"     Subject: {c.get('subject', '')[:60]}")
            print()

    # Auto-reply to INFO_REQUESTs with clear answers
    info_requests = [r for r in new_replies if r["classification"] == "INFO_REQUEST"]
    if info_requests and GMAIL_APP_PASSWORD:
        print(f"\n📋 Auto-replying to {len(info_requests)} info request(s)...")
        for r in info_requests:
            _send_info_reply(r["email"], r["subject"])

    # Auto-reply to INTERVIEW_SCHEDULED with YOUR calendar link
    # BUT: if recruiter already sent THEIR calendar link, don't reply — you need to book on THEIRS
    interviews = [r for r in new_replies if r["classification"] == "INTERVIEW_SCHEDULED"]
    if interviews and GMAIL_APP_PASSWORD:
        import re
        calendar_link_pattern = re.compile(
            r"calendly\.com|hubspot\.com/meetings|outlook\.office\.com/bookings|"
            r"cal\.com/|doodle\.com|schedule\..*\.com|booking\.|"
            r"chili.*piper|acuity.*scheduling|appointlet|youcanbook",
            re.I
        )
        for r in interviews:
            body = r.get("body_preview", "") + r.get("subject", "")
            if calendar_link_pattern.search(body):
                # They sent THEIR calendar — auto-reply with 24hr commitment
                print(f"   📅 {r['email']} sent THEIR calendar link — auto-replying with 24hr commitment")
                _send_calendar_ack_reply(r["email"], r["subject"])
            else:
                # They asked to schedule but no link — send YOUR calendar
                print(f"   📅 Auto-replying to {r['email']} with your calendar link...")
                _send_interview_reply(r["email"], r["subject"])


def _send_calendar_ack_reply(to_email: str, original_subject: str):
    """When recruiter sends THEIR calendar link — auto-reply confirming you'll book within 24h."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    subject = f"Re: {original_subject}" if not original_subject.startswith("Re:") else original_subject

    html = """<div style="font-family:Arial,sans-serif;font-size:14px;color:#333">
<p>Hi,</p>

<p>Thank you! I'll review your calendar and book a slot within the next 24 hours.</p>

<p><strong>My timezone:</strong> Mountain Time (MT / Colorado, UTC-6)<br>
<strong>Preferred times:</strong> Mon–Fri, 9 AM – 5 PM MT<br>
<strong>Format:</strong> Zoom, Google Meet, Teams, or phone — all work.</p>

<p>Looking forward to connecting!</p>

<p>Best regards,<br>Bob Rikh<br>347-268-5917</p>
</div>"""

    plain = """Hi,

Thank you! I'll review your calendar and book a slot within the next 24 hours.

My timezone: Mountain Time (MT / Colorado, UTC-6)
Preferred times: Mon-Fri, 9 AM - 5 PM MT
Format: Zoom, Google Meet, Teams, or phone — all work.

Looking forward to connecting!

Best regards,
Bob Rikh
347-268-5917"""

    msg = MIMEMultipart("alternative")
    msg["From"] = f"Bob Rikh <{GMAIL_USER}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = GMAIL_USER
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.starttls()
            s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            s.send_message(msg)
        print(f"   ✅ Sent 24hr booking commitment to {to_email}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")


def _send_interview_reply(to_email: str, original_subject: str):
    """Auto-reply to interview requests with YOUR Google Calendar booking link.
    Recruiter picks a time that works for BOTH of you."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    subject = f"Re: {original_subject}" if not original_subject.startswith("Re:") else original_subject

    html = """<div style="font-family:Arial,sans-serif;font-size:14px;color:#333">
<p>Hi,</p>

<p>Thank you for your interest! I'd love to connect.</p>

<p>Please pick a time that works for you — my calendar shows only my available slots:</p>

<p style="margin:15px 0">
  <a href="https://calendar.app.google/DG7ug2xFUuQneV2r6" 
     style="background:#1a73e8;color:white;padding:12px 24px;text-decoration:none;border-radius:5px;font-weight:bold">
     📅 Book a Time on My Calendar
  </a>
</p>

<p>This automatically syncs with my schedule — any slot you see is confirmed available.</p>

<p><strong>My timezone:</strong> Mountain Time (MT / UTC-6)<br>
<strong>Preferred format:</strong> Zoom, Google Meet, or phone — all work for me.</p>

<p>Looking forward to speaking with you!</p>

<p>Best regards,<br>Bob Rikh<br>347-268-5917</p>
</div>"""

    plain = """Hi,

Thank you for your interest! I'd love to connect.

Please pick a time that works for you:
https://calendar.app.google/DG7ug2xFUuQneV2r6

This automatically syncs with my schedule — any slot you see is confirmed available.

Timezone: Mountain Time (MT / UTC-6)
Preferred format: Zoom, Google Meet, or phone — all work.

Looking forward to speaking with you!

Best regards,
Bob Rikh
347-268-5917"""

    msg = MIMEMultipart("alternative")
    msg["From"] = f"Bob Rikh <{GMAIL_USER}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = GMAIL_USER
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.starttls()
            s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            s.send_message(msg)
        print(f"   ✅ Interview reply sent to {to_email} (with calendar link)")
    except Exception as e:
        print(f"   ❌ Failed: {e}")


def _send_info_reply(to_email: str, original_subject: str):
    """Auto-reply to recruiter info requests with clear, direct answers.
    No guessing — just facts."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    subject = f"Re: {original_subject}" if not original_subject.startswith("Re:") else original_subject

    html = """<div style="font-family:Arial,sans-serif;font-size:14px;color:#333">
<p>Hello,</p>

<p>Thank you for your reply. Here are my details:</p>

<table style="border-collapse:collapse;margin:10px 0">
<tr><td style="padding:4px 15px 4px 0;font-weight:bold">Work Type:</td><td>C2C / Corp-to-Corp ONLY (no W2)</td></tr>
<tr><td style="padding:4px 15px 4px 0;font-weight:bold">Rate:</td><td>$70–95/hr C2C (flexible based on project duration/scope)</td></tr>
<tr><td style="padding:4px 15px 4px 0;font-weight:bold">Availability:</td><td>Immediate — can start within 2 weeks</td></tr>
<tr><td style="padding:4px 15px 4px 0;font-weight:bold">Location:</td><td>Parker, CO — Remote preferred, open to hybrid in Denver metro</td></tr>
<tr><td style="padding:4px 15px 4px 0;font-weight:bold">Authorization:</td><td>Green Card holder — NO sponsorship required</td></tr>
<tr><td style="padding:4px 15px 4px 0;font-weight:bold">Experience:</td><td>8+ years Java Backend (Spring Boot, Kafka, K8s, AWS)</td></tr>
<tr><td style="padding:4px 15px 4px 0;font-weight:bold">Current Role:</td><td>Java Backend Developer at Charter Communications (Spectrum)</td></tr>
</table>

<p>Happy to schedule a quick call to discuss further. You can book directly here:<br>
<a href="https://calendar.app.google/DG7ug2xFUuQneV2r6">📅 Book a 15-min call</a></p>

<p>Best regards,<br>Bob Rikh</p>
</div>"""

    plain = """Hello,

Thank you for your reply. Here are my details:

- Work Type: C2C / Corp-to-Corp ONLY (no W2)
- Rate: $70-95/hr C2C (flexible based on project duration/scope)
- Availability: Immediate — can start within 2 weeks
- Location: Parker, CO — Remote preferred, open to hybrid in Denver metro
- Authorization: Green Card holder — NO sponsorship required
- Experience: 8+ years Java Backend (Spring Boot, Kafka, K8s, AWS)
- Current Role: Java Backend Developer at Charter Communications (Spectrum)

Happy to schedule a quick call:
https://calendar.app.google/DG7ug2xFUuQneV2r6

Best regards,
Bob Rikh
347-268-5917
bobrikh75@gmail.com"""

    msg = MIMEMultipart("alternative")
    msg["From"] = f"Bob Rikh <{GMAIL_USER}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = GMAIL_USER
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.starttls()
            s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            s.send_message(msg)
        print(f"   ✅ Auto-replied to {to_email} with rate/availability info")
    except Exception as e:
        print(f"   ❌ Failed to auto-reply to {to_email}: {e}")


if __name__ == "__main__":
    main()
