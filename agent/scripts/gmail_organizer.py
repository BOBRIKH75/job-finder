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
LABELS = {
    "Jobs": None,  # parent
    "Jobs/Recruiters": None,
    "Jobs/Applications": None,
    "Jobs/Interviews": None,
    "Jobs/Rejections": None,
    "Jobs/Auto-Replies": None,
    "Jobs/Info-Requests": None,
}

# Classification keywords
INTERVIEW_KW = re.compile(r"schedul|interview|call.*with|zoom|teams|phone screen|pick a time|when.*available", re.I)
REJECTION_KW = re.compile(r"position.*filled|moved forward with other|not a match|unfortunately|regret to inform|no longer", re.I)
APPLICATION_KW = re.compile(r"application.*received|thank.*applying|submission.*confirm|we.*received.*resume", re.I)
AUTO_REPLY_KW = re.compile(r"out of office|automatic reply|auto-reply|OOO|currently away", re.I)
INFO_REQUEST_KW = re.compile(r"rate|availability|visa|authorization|resume|when.*start", re.I)

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
    """Classify email into a label category."""
    text = f"{subject} {body}"
    from_domain = from_addr.split("@")[-1].lower().strip(">")
    
    # Check domain first
    if from_domain in APPLICATION_DOMAINS:
        if INTERVIEW_KW.search(text):
            return "Jobs/Interviews"
        return "Jobs/Applications"
    
    if from_domain in RECRUITER_DOMAINS:
        if INTERVIEW_KW.search(text):
            return "Jobs/Interviews"
        if REJECTION_KW.search(text):
            return "Jobs/Rejections"
        if INFO_REQUEST_KW.search(text):
            return "Jobs/Info-Requests"
        return "Jobs/Recruiters"
    
    # Check content keywords
    if AUTO_REPLY_KW.search(text):
        return "Jobs/Auto-Replies"
    if INTERVIEW_KW.search(text):
        return "Jobs/Interviews"
    if APPLICATION_KW.search(text):
        return "Jobs/Applications"
    if REJECTION_KW.search(text):
        return "Jobs/Rejections"
    
    return None  # Don't label — not job-related


def organize_inbox(conn, days_back=7):
    """Scan recent inbox emails and apply labels."""
    conn.select("INBOX")
    
    # Search recent emails
    import datetime
    since = (datetime.datetime.now() - datetime.timedelta(days=days_back)).strftime("%d-%b-%Y")
    _, data = conn.search(None, f'(SINCE "{since}")')
    
    msg_ids = data[0].split()
    print(f"  Scanning {len(msg_ids)} emails from last {days_back} days...")
    
    labeled = {"Jobs/Recruiters": 0, "Jobs/Applications": 0, "Jobs/Interviews": 0,
               "Jobs/Rejections": 0, "Jobs/Auto-Replies": 0, "Jobs/Info-Requests": 0}
    
    for msg_id in msg_ids:
        try:
            _, msg_data = conn.fetch(msg_id, "(RFC822.HEADER BODY[TEXT])")
            raw = msg_data[0][1] if msg_data[0][1] else b""
            msg = email.message_from_bytes(raw)
            
            from_addr = msg.get("From", "")
            subject = msg.get("Subject", "")
            
            # Decode subject
            decoded = decode_header(subject)
            subject = "".join(
                part.decode(charset or "utf-8", errors="ignore") if isinstance(part, bytes) else part
                for part, charset in decoded
            )
            
            body = get_body(msg)
            label = classify_email(from_addr, subject, body)
            
            if label:
                # Apply label (copy to label folder)
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
