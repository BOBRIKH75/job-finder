#!/usr/bin/env python3
"""
Backup calendar booking alerter — runs in GitHub Actions every 10 minutes.
Checks Gmail IMAP for Google Calendar booking emails.
If new booking found: pushes ntfy.sh alert + sends email via Resend.

Primary alert: Google Apps Script (scripts/calendar_booking_alert.gs)
This is the backup in case Apps Script misses something.
"""
import imaplib
import email
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

GMAIL_USER = os.environ.get("GMAIL_USER", "bobrikh75@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
RESEND_KEY = os.environ.get("RESEND_KEY", "")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", GMAIL_USER)

SEEN_FILE = Path("data/calendar_seen_bookings.json")


def load_seen() -> set:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen: set):
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2))


def check_gmail_for_bookings() -> list[dict]:
    """Check Gmail IMAP for new Google Calendar booking emails in the last 30 minutes."""
    if not GMAIL_APP_PASSWORD:
        print("No GMAIL_APP_PASSWORD — skipping IMAP check")
        return []

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        mail.select("inbox")

        # Search for booking notification emails from Google Calendar
        since = (datetime.now() - timedelta(minutes=30)).strftime("%d-%b-%Y")
        status, data = mail.search(
            None,
            '(FROM "calendar-notification@google.com" SINCE ' + since + ')',
        )
        if status != "OK" or not data[0]:
            mail.logout()
            return []

        bookings = []
        msg_ids = data[0].split()
        for msg_id in msg_ids[-10:]:  # check last 10 max
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK":
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            subject = msg.get("Subject", "")
            msg_uid = msg.get("Message-ID", str(msg_id))

            # Only alert for new booking subjects
            subject_lower = subject.lower()
            if not any(k in subject_lower for k in [
                "new appointment", "appointment booked", "booking confirmed",
                "new booking", "appointment scheduled",
            ]):
                continue

            # Extract body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

            bookings.append({
                "uid": msg_uid,
                "subject": subject,
                "body": body[:400].strip(),
                "date": msg.get("Date", ""),
            })

        mail.logout()
        return bookings

    except Exception as e:
        print(f"IMAP error: {e}")
        return []


def push_ntfy(subject: str, body: str):
    """Push urgent notification to ntfy.sh."""
    if not NTFY_TOPIC:
        return
    import urllib.request
    payload = body.encode()
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=payload,
        headers={
            "Title": f"📅 {subject}",
            "Priority": "urgent",
            "Tags": "calendar,tada",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        print(f"  ✅ ntfy alert sent: {subject[:60]}")
    except Exception as e:
        print(f"  ⚠️ ntfy failed: {e}")


def send_email_alert(subject: str, body: str):
    """Send email alert via Resend."""
    if not RESEND_KEY:
        return
    import urllib.request
    payload = json.dumps({
        "from": "Job Agent <onboarding@resend.dev>",
        "to": [ALERT_EMAIL],
        "subject": f"📅 CALENDAR BOOKING: {subject}",
        "text": f"New recruiter booking detected!\n\n{body}\n\n---\nReply quickly — they're waiting.",
    }).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {RESEND_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=15)
        print(f"  ✅ Email alert sent to {ALERT_EMAIL}")
    except Exception as e:
        print(f"  ⚠️ Email alert failed: {e}")


def main():
    print(f"[{datetime.now().strftime('%H:%M')}] Checking Gmail for new calendar bookings...")

    bookings = check_gmail_for_bookings()
    if not bookings:
        print("  No new bookings found")
        return

    seen = load_seen()
    new_count = 0

    for b in bookings:
        uid = b["uid"]
        if uid in seen:
            continue

        print(f"  🎉 NEW BOOKING: {b['subject']}")
        push_ntfy(b["subject"], b["body"])
        send_email_alert(b["subject"], b["body"])
        seen.add(uid)
        new_count += 1

    if new_count:
        save_seen(seen)
        print(f"  Total new bookings alerted: {new_count}")
    else:
        print("  All recent booking emails already alerted")


if __name__ == "__main__":
    main()
