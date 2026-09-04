#!/usr/bin/env python3
"""
Gmail Auto-Organizer — Labels/folders for job search emails.

MOVE semantics: emails are copied to the correct label AND removed from inbox
(archived). In Gmail IMAP, marking \\Deleted in INBOX removes the Inbox label
while keeping the message in All Mail + the destination label.

Run modes:
  python gmail_organizer.py             # last 7 days (daily use)
  python gmail_organizer.py --backfill  # ALL emails since 2024 (one-time setup)
"""
import argparse
import imaplib
import email
import os
import re
import sqlite3
import sys
from email.header import decode_header
from pathlib import Path

GMAIL_USER = os.environ.get("GMAIL_USER", "bobrikh75@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
DB_PATH = Path(__file__).parent.parent / "data" / "agent_memory.db"

LABELS = {
    "Jobs": None,
    "Jobs/ACTION-Interviews": None,
    "Jobs/ACTION-Inbound": None,
    "Jobs/Recruiters": None,
    "Jobs/Applications": None,
    "Jobs/Acknowledged": None,
    "Jobs/Info-Requests": None,
    "Jobs/Rejections": None,
    "Jobs/Auto-Replies": None,
    "Jobs/Failed": None,
    "Jobs/Spam": None,
}

INTERVIEW_KW = re.compile(
    r"schedul|interview|call.*with|zoom|teams|phone screen|pick a time|"
    r"when.*available|calendly|cal\.com|invite you|meeting request|google meet|"
    r"technical assessment|coding challenge|hackerrank|codility", re.I)
REJECTION_KW = re.compile(
    r"position.*filled|moved forward with other|not a match|unfortunately|"
    r"regret to inform|no longer|decided not to|other candidate|wish you well", re.I)
APPLICATION_KW = re.compile(
    r"application.*received|thank.*applying|submission.*confirm|"
    r"we.*received.*resume|application.*submitted|thanks for applying", re.I)
AUTO_REPLY_KW = re.compile(
    r"out of office|automatic reply|auto-reply|OOO|currently away|"
    r"on vacation|will be back|returning on", re.I)
INFO_REQUEST_KW = re.compile(
    r"\brate\b|availability|visa status|work authorization|"
    r"resume.*attached|when.*start|open to.*role|looking for.*role", re.I)
ACKNOWLEDGED_KW = re.compile(
    r"thank.*for.*(reaching|sending|your)|received.*resume|will.*review|"
    r"under.*review|keep.*on\s*file|added.*database|in our system|pipeline", re.I)
BOUNCE_KW = re.compile(
    r"delivery.*fail|undeliverable|returned.*mail|mailbox.*full|"
    r"address.*rejected|550.*reject|user.*unknown|no.*such.*user", re.I)
SPAM_KW = re.compile(
    r"unsubscribe|click here to|limited time|act now|congratulations.*won|"
    r"earn.*\$.*from home|MLM|crypto.*opportunity|marketing.*automation|bulk email", re.I)
INBOUND_KW = re.compile(
    r"(found|saw|noticed|came across)\s*(your|you).*(profile|linkedin|resume|background)|"
    r"we.*(have|got)\s*a.*position.*for you|would you be (interested|open)|"
    r"reaching out.*because.*your (profile|experience)|came across your", re.I)

BOUNCE_SENDERS = {"mailer-daemon@", "postmaster@", "noreply@google.com"}
SPAM_DOMAINS = {"marketing.", "promo.", "newsletter.", "offers.", "deals.",
                "noreply@", "bulk@", "campaign@", "blast@"}
RECRUITER_DOMAINS = {
    "collabera.com", "pyramidci.com", "mastechdigital.com", "skiltrek.com",
    "talentburst.com", "kforce.com", "teksystems.com", "motionrecruitment.com",
    "bartechstaffing.com", "hanstaffing.com", "sansomstaffing.com",
    "pacerstaffing.com", "synergystaffing.com", "brillfy.com", "unitedtekinfo.com",
    "cybercoders.com", "modis.com", "insight.com", "softpath.net", "randstad.com",
    "adecco.com", "manpower.com", "sapient.com", "cognizant.com", "infosys.com",
}
APPLICATION_DOMAINS = {
    "greenhouse.io", "lever.co", "indeed.com", "dice.com", "linkedin.com",
    "jobvite.com", "ashbyhq.com", "workday.com", "icims.com", "myworkdayjobs.com",
    "greenhouse-mail.io", "us.greenhouse-mail.io", "notifications.dice.com",
    "mail.lever.co", "indeedmail.com",
}
STAFFING_SIGNALS = ["staffing", "recruit", "consult", "talent", "hiring", "hr",
                    "workforce", "placement", "search", "solutions"]


def load_known_data() -> tuple[set, set]:
    recruiter_emails: set = set()
    applied_companies: set = set()
    if not DB_PATH.exists():
        return recruiter_emails, applied_companies
    try:
        db = sqlite3.connect(str(DB_PATH))
        for row in db.execute("SELECT email FROM recruiters").fetchall():
            if row[0]:
                recruiter_emails.add(row[0].lower().strip())
        for row in db.execute(
            "SELECT company FROM applications WHERE status IN ('applied','submitted')"
        ).fetchall():
            if row[0]:
                applied_companies.add(row[0].lower().strip())
        db.close()
    except Exception as exc:
        print(f"  ⚠️ DB load warning: {exc}")
    return recruiter_emails, applied_companies


def connect():
    import socket
    socket.setdefaulttimeout(30)
    conn = imaplib.IMAP4_SSL("imap.gmail.com")
    conn.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    return conn


def ensure_labels(conn):
    _, existing = conn.list()
    existing_names = set()
    for item in (existing or []):
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
                pass


def classify_email(
    from_addr: str,
    subject: str,
    body: str,
    recruiter_emails: set,
    applied_companies: set,
) -> str | None:
    text = f"{subject} {body}"
    from_lower = from_addr.lower()
    m = re.search(r'[\w.+-]+@[\w.-]+', from_lower)
    from_email = m.group(0) if m else from_lower
    from_domain = from_email.split("@")[-1] if "@" in from_email else from_lower
    is_reply = subject.strip().lower().startswith("re:")
    mentions_bob = bool(re.search(r"bob|rikh|c2c|java.*backend", text, re.I))

    # 1. Bounce
    if any(s in from_lower for s in BOUNCE_SENDERS) or BOUNCE_KW.search(text):
        return "Jobs/Failed"

    # 2. Spam (never tag replies or emails that mention us)
    if not is_reply and not mentions_bob:
        if SPAM_KW.search(text) or any(s in from_lower for s in SPAM_DOMAINS):
            return "Jobs/Spam"

    # 3. Interview — highest value, always surface first
    if INTERVIEW_KW.search(text):
        return "Jobs/ACTION-Interviews"

    # 4. Known recruiter from DB — classify by content, never miss
    if from_email in recruiter_emails:
        if REJECTION_KW.search(text):
            return "Jobs/Rejections"
        if AUTO_REPLY_KW.search(text):
            return "Jobs/Auto-Replies"
        if INTERVIEW_KW.search(text):
            return "Jobs/ACTION-Interviews"
        if INFO_REQUEST_KW.search(text):
            return "Jobs/Info-Requests"
        if ACKNOWLEDGED_KW.search(text):
            return "Jobs/Acknowledged"
        return "Jobs/Recruiters"

    # 5. Inbound — recruiter found YOU
    if INBOUND_KW.search(text) and not is_reply:
        return "Jobs/ACTION-Inbound"

    # 6. Application confirmation domains
    if from_domain in APPLICATION_DOMAINS:
        if REJECTION_KW.search(text):
            return "Jobs/Rejections"
        return "Jobs/Applications"

    # 7. Known recruiter domains
    if from_domain in RECRUITER_DOMAINS:
        if REJECTION_KW.search(text):
            return "Jobs/Rejections"
        if INFO_REQUEST_KW.search(text):
            return "Jobs/Info-Requests"
        if ACKNOWLEDGED_KW.search(text):
            return "Jobs/Acknowledged"
        return "Jobs/Recruiters"

    # 8. Content fallback for unknown senders
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

    # 9. Safety net — reply to our outreach
    if is_reply and (mentions_bob or "C2C" in subject or "Java" in subject):
        return "Jobs/Recruiters"

    # 10. Staffing/consulting domain signal
    if any(s in from_domain for s in STAFFING_SIGNALS):
        return "Jobs/Recruiters"

    return None  # Not job-related — leave in inbox


def organize_inbox(conn, recruiter_emails: set, applied_companies: set,
                   days_back: int = 7, batch_limit: int = 200):
    """Scan INBOX, classify each email, MOVE it to the correct label folder.

    MOVE = copy to label + mark \\Deleted in INBOX + expunge.
    In Gmail IMAP this removes the Inbox label while keeping the message
    in All Mail and the destination label — same as Gmail's archive+label.
    """
    conn.select("INBOX")

    import datetime
    since = (datetime.datetime.now() - datetime.timedelta(days=days_back)).strftime("%d-%b-%Y")
    _, data = conn.search(None, f'(SINCE "{since}")')
    msg_ids = data[0].split() if data[0] else []
    msg_ids = msg_ids[-batch_limit:]
    print(f"  Scanning {len(msg_ids)} emails (last {days_back} days, limit {batch_limit})...")

    labeled: dict = {}
    moved_ids: list = []

    for msg_id in reversed(msg_ids):
        try:
            _, msg_data = conn.fetch(msg_id, "(RFC822.HEADER)")
            if not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else b""
            msg = email.message_from_bytes(raw)

            from_addr = msg.get("From", "")
            subject_raw = msg.get("Subject", "")
            decoded = decode_header(subject_raw)
            subject = "".join(
                part.decode(charset or "utf-8", errors="ignore")
                if isinstance(part, bytes) else part
                for part, charset in decoded
            )

            label = classify_email(from_addr, subject, "", recruiter_emails, applied_companies)

            if label:
                copied = False
                try:
                    conn.copy(msg_id, f'"{label}"')
                    copied = True
                except Exception:
                    try:
                        conn.copy(msg_id, label)
                        copied = True
                    except Exception:
                        pass

                if copied:
                    # Mark for removal from INBOX (archive in Gmail)
                    conn.store(msg_id, '+FLAGS', '(\\Deleted)')
                    moved_ids.append(msg_id)
                    labeled[label] = labeled.get(label, 0) + 1

        except Exception:
            continue

    # Finalize all moves in one shot
    if moved_ids:
        conn.expunge()
        print(f"  📦 Moved {len(moved_ids)} emails out of inbox")

    return labeled


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true",
                        help="Process ALL emails since 2024 (one-time setup)")
    args = parser.parse_args()

    if not GMAIL_APP_PASSWORD:
        print("❌ GMAIL_APP_PASSWORD not set")
        sys.exit(1)

    print("📁 Gmail Auto-Organizer")
    print("═" * 40)

    recruiter_emails, applied_companies = load_known_data()
    print(f"  📊 Loaded {len(recruiter_emails)} known recruiters, "
          f"{len(applied_companies)} applied companies from DB")

    conn = connect()
    print("  ✅ Connected to Gmail")

    ensure_labels(conn)

    if args.backfill:
        print("  🔄 BACKFILL MODE — processing all emails since 2024...")
        results = organize_inbox(conn, recruiter_emails, applied_companies,
                                 days_back=730, batch_limit=2000)
    else:
        results = organize_inbox(conn, recruiter_emails, applied_companies,
                                 days_back=7, batch_limit=200)

    conn.logout()

    print(f"\n📊 Moved to folders:")
    total = 0
    for label, count in sorted(results.items()):
        if count > 0:
            print(f"   {label}: {count} emails")
            total += count

    if total == 0:
        print("   No new job emails to organize")
    else:
        print(f"   Total: {total} emails moved out of inbox")


if __name__ == "__main__":
    main()
