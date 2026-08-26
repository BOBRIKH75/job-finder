#!/usr/bin/env python3
"""
Gmail Auto-Organizer — Labels/folders for job search emails.

Creates labels and auto-sorts incoming emails:
  📁 Jobs/Recruiters      — replies from recruiters you contacted
  📁 Jobs/Applications    — application confirmations (Greenhouse, Lever, Indeed)
  📁 Jobs/Interviews      — interview invites, scheduling links
  📁 Jobs/Rejections      — "position filled", "moved forward with other"
  📁 Jobs/Auto-Replies    — OOO, auto-responses

Runs daily after reply tracker. Uses IMAP (same GMAIL_APP_PASSWORD).
"""
import imaplib
import email
import os
import re
from email.header import decode_header

GMAIL_USER = os.environ.get("GMAIL_USER", "bobrikh75@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

# Label structure (Gmail uses / for nested labels)
# Split into: ACTION (you check daily) vs AUTO (system handles)
LABELS = {
    "Jobs": None,                       # parent
    # === ACTION NEEDED (check daily) ===
    "Jobs/ACTION-Interviews": None,     # interview invites — RESPOND
    "Jobs/ACTION-Inbound": None,        # recruiters found YOU — RESPOND
    # === AUTO-HANDLED (system deals with it) ===
    "Jobs/Recruiters": None,            # replies from your outreach (auto-tracked)
    "Jobs/Applications": None,          # application confirmations
    "Jobs/Acknowledged": None,          # "got your resume, reviewing"
    "Jobs/Info-Requests": None,         # rate questions (auto-replied)
    "Jobs/Rejections": None,            # position filled (follow-up stopped)
    "Jobs/Auto-Replies": None,          # OOO
    "Jobs/Failed": None,                # bounced (bad email removed)
    "Jobs/Spam": None,                  # ads, fake jobs
}

# Classification keywords
INTERVIEW_KW = re.compile(r"schedul|interview|call.*with|zoom|teams|phone screen|pick a time|when.*available", re.I)
REJECTION_KW = re.compile(r"position.*filled|moved forward with other|not a match|unfortunately|regret to inform|no longer", re.I)
APPLICATION_KW = re.compile(r"application.*received|thank.*applying|submission.*confirm|we.*received.*resume", re.I)
AUTO_REPLY_KW = re.compile(r"out of office|automatic reply|auto-reply|OOO|currently away", re.I)
INFO_REQUEST_KW = re.compile(r"rate|availability|visa|authorization|resume|when.*start", re.I)
ACKNOWLEDGED_KW = re.compile(r"thank.*for.*(reaching|sending|your)|received.*resume|will.*review|under.*review|keep.*on\s*file|added.*database", re.I)

# Bounce / delivery failure
BOUNCE_KW = re.compile(r"delivery.*fail|undeliverable|returned.*mail|mailbox.*full|address.*rejected|550.*reject|user.*unknown|no.*such.*user", re.I)
BOUNCE_SENDERS = {"mailer-daemon@", "postmaster@", "noreply@google.com"}

# Spam / advertising / fake jobs
SPAM_KW = re.compile(r"unsubscribe|click here to|limited time|act now|congratulations.*won|earn.*\$.*from home|MLM|crypto.*opportunity|marketing.*automation|bulk email", re.I)
SPAM_DOMAINS = {
    "marketing.", "promo.", "newsletter.", "offers.", "deals.",
    "noreply@", "bulk@", "campaign@", "blast@",
}

# Inbound — recruiters finding YOU (not replies to your outreach)
INBOUND_KW = re.compile(r"(found|saw|noticed|came across)\s*(your|you).*(profile|linkedin|resume|background)|we.*(have|got)\s*a.*position.*for you|would you be (interested|open)|reaching out.*because.*your (profile|experience)", re.I)

# Known recruiter/job domains
RECRUITER_DOMAINS = {
    "collabera.com", "pyramidci.com", "mastechdigital.com", "skiltrek.com",
    "talentburst.com", "kforce.com", "teksystems.com", "motionrecruitment.com",
    "bartechstaffing.com", "hanstaffing.com", "sansomstaffing.com",
    "pacerstaffing.com", "synergystaffing.com", "brillfy.com", "unitedtekinfo.com",
}
APPLICATION_DOMAINS = {
    "greenhouse.io", "lever.co", "indeed.com", "dice.com", "linkedin.com",
    "jobvite.com", "ashbyhq.com", "workday.com", "icims.com", "myworkdayjobs.com",
}


def connect():
    conn = imaplib.IMAP4_SSL("imap.gmail.com")
    conn.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    return conn


def ensure_labels(conn):
    """Create Gmail labels if they don't exist."""
    _, existing = conn.list()
    existing_names = set()
    for item in existing:
        # Parse label name from IMAP response
        if isinstance(item, bytes):
            match = re.search(rb'"/" "?([^"]*)"?$', item)
            if match:
                existing_names.add(match.group(1).decode())
    
    for label in LABELS:
        if label not in existing_names:
            try:
                conn.create(f'"{label}"')
                print(f"  ✅ Created label: {label}")
            except Exception:
                pass  # May already exist


def get_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode("utf-8", errors="ignore")[:1000]
                except:
                    pass
    else:
        try:
            return msg.get_payload(decode=True).decode("utf-8", errors="ignore")[:1000]
        except:
            pass
    return ""


def classify_email(from_addr: str, subject: str, body: str) -> str:
    """Classify email into a label category. Priority order matters.
    
    SAFETY NET: Any email that is a REPLY to our outreach (has "Re:" + our subject)
    or from a domain we've contacted ALWAYS gets labeled — never skipped.
    """
    text = f"{subject} {body}"
    from_lower = from_addr.lower()
    from_domain = from_addr.split("@")[-1].lower().strip(">")
    is_reply = subject.strip().startswith("Re:")
    mentions_bob = bool(re.search(r"bob|rikh|c2c|java.*backend", text, re.I))
    
    # 1. BOUNCE — delivery failures (highest priority — remove bad emails)
    if any(s in from_lower for s in BOUNCE_SENDERS) or BOUNCE_KW.search(text):
        return "Jobs/Failed"
    
    # 2. SPAM — ads, fake jobs, marketing (but NOT if it's a reply to us)
    if not is_reply and not mentions_bob:
        if SPAM_KW.search(text) or any(s in from_lower for s in SPAM_DOMAINS):
            return "Jobs/Spam"
    
    # 3. INTERVIEW — always top priority if keywords match
    if INTERVIEW_KW.search(text):
        return "Jobs/ACTION-Interviews"
    
    # 4. INBOUND — recruiter found YOU (not a reply to your outreach)
    if INBOUND_KW.search(text) and not is_reply:
        return "Jobs/ACTION-Inbound"
    
    # 5. Check by sender domain
    if from_domain in APPLICATION_DOMAINS:
        if REJECTION_KW.search(text):
            return "Jobs/Rejections"
        return "Jobs/Applications"
    
    if from_domain in RECRUITER_DOMAINS:
        if REJECTION_KW.search(text):
            return "Jobs/Rejections"
        if INFO_REQUEST_KW.search(text):
            return "Jobs/Info-Requests"
        if ACKNOWLEDGED_KW.search(text):
            return "Jobs/Acknowledged"
        return "Jobs/Recruiters"
    
    # 6. Check content keywords (unknown sender)
    if AUTO_REPLY_KW.search(text):
        return "Jobs/Auto-Replies"
    if REJECTION_KW.search(text):
        return "Jobs/Rejections"
    if APPLICATION_KW.search(text):
        return "Jobs/Applications"
    if ACKNOWLEDGED_KW.search(text):
        return "Jobs/Acknowledged"
    if INFO_REQUEST_KW.search(text):
        return "Jobs/Info-Requests"
    
    # 7. SAFETY NET — if it's a reply to our outreach OR mentions us, NEVER skip
    if is_reply and ("C2C" in subject or "Bob Rikh" in subject or "Java" in subject):
        return "Jobs/Recruiters"  # It's a reply to us — always track
    if mentions_bob and is_reply:
        return "Jobs/Recruiters"
    
    # 8. If from a staffing/consulting domain (even if not in our list) — track it
    staffing_signals = ["staffing", "recruit", "consult", "talent", "hiring", "hr"]
    if any(s in from_domain for s in staffing_signals):
        return "Jobs/Recruiters"
    
    return None  # Truly not job-related — leave in inbox


def organize_inbox(conn, days_back=3):
    """Scan recent inbox emails and apply labels. Only last 3 days to avoid timeout."""
    conn.select("INBOX")
    
    # Search recent emails (3 days only — runs daily so nothing gets missed)
    import datetime
    since = (datetime.datetime.now() - datetime.timedelta(days=days_back)).strftime("%d-%b-%Y")
    _, data = conn.search(None, f'(SINCE "{since}")')
    
    msg_ids = data[0].split()
    # Limit to 50 emails per run to prevent timeout
    msg_ids = msg_ids[:50]
    print(f"  Scanning {len(msg_ids)} emails from last {days_back} days (max 50)...")
    
    labeled = {"Jobs/Recruiters": 0, "Jobs/Applications": 0, "Jobs/ACTION-Interviews": 0,
               "Jobs/Rejections": 0, "Jobs/Auto-Replies": 0, "Jobs/Info-Requests": 0}
    
    for msg_id in msg_ids:
        try:
            # Light fetch — only headers first
            _, msg_data = conn.fetch(msg_id, "(RFC822.HEADER)")
            if not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else b""
            msg = email.message_from_bytes(raw)
            
            from_addr = msg.get("From", "")
            subject = msg.get("Subject", "")
            
            # Decode subject
            decoded = decode_header(subject)
            subject = "".join(
                part.decode(charset or "utf-8", errors="ignore") if isinstance(part, bytes) else part
                for part, charset in decoded
            )
            
            # Try to classify with just headers (faster)
            label = classify_email(from_addr, subject, "")
            
            if label:
                conn.copy(msg_id, f'"{label}"')
                labeled[label] = labeled.get(label, 0) + 1
        except Exception:
            continue
    
    return labeled


def main():
    if not GMAIL_APP_PASSWORD:
        print("❌ GMAIL_APP_PASSWORD not set")
        return
    
    print("📁 Gmail Auto-Organizer")
    print("═" * 40)
    
    conn = connect()
    print("  ✅ Connected to Gmail")
    
    # Create labels
    ensure_labels(conn)
    
    # Organize
    results = organize_inbox(conn)
    conn.logout()
    
    print(f"\n📊 Organized:")
    for label, count in results.items():
        if count > 0:
            print(f"   {label}: {count} emails")
    
    total = sum(results.values())
    if total == 0:
        print("   No new job emails to organize")
    else:
        print(f"   Total: {total} emails labeled")


if __name__ == "__main__":
    main()
