#!/usr/bin/env python3
"""
Application Confirmation Tracker — checks Gmail for "thank you for applying" emails.

Counts REAL confirmed applications by reading company confirmation emails.
This is the GROUND TRUTH — if you got the email, the company received your application.

Run: python agent/scripts/application_confirmations.py
"""
import imaplib
import email
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

GMAIL_USER = os.environ.get("GMAIL_USER", "bobrikh75@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

CONFIRMATIONS_FILE = Path(__file__).parent.parent / "data" / "application_confirmations.json"

# Keywords that indicate a real application confirmation
CONFIRMATION_SIGNALS = [
    "thank you for applying",
    "thanks for applying", 
    "application received",
    "we received your application",
    "application has been submitted",
    "successfully submitted",
    "thank you for your interest",
    "thanks for your interest",
    "we have received your resume",
    "application confirmation",
    "your application for",
]

# Senders to IGNORE (not real confirmations)
IGNORE_SENDERS = [
    "noreply@github.com",
    "notifications@github.com",
    "resend.dev",
]


def count_confirmations(days_back=1) -> dict:
    """Count application confirmation emails from last N days."""
    if not GMAIL_APP_PASSWORD:
        print("⚠️ GMAIL_APP_PASSWORD not set — cannot check confirmations")
        return {"count": 0, "companies": []}

    try:
        conn = imaplib.IMAP4_SSL("imap.gmail.com")
        conn.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        conn.select("INBOX")

        since_date = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
        _, msg_nums = conn.search(None, f'(SINCE "{since_date}")')

        confirmations = []
        for num in msg_nums[0].split():
            _, data = conn.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(data[0][1])

            sender = msg.get("From", "").lower()
            subject = msg.get("Subject", "").lower()

            # Skip ignored senders
            if any(ig in sender for ig in IGNORE_SENDERS):
                continue

            # Check subject and body for confirmation signals
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        try:
                            body = part.get_payload(decode=True).decode("utf-8", errors="ignore").lower()
                        except Exception:
                            pass
                        break
            else:
                try:
                    body = msg.get_payload(decode=True).decode("utf-8", errors="ignore").lower()
                except Exception:
                    pass

            text = subject + " " + body[:500]
            if any(signal in text for signal in CONFIRMATION_SIGNALS):
                # Extract company name from sender
                company = re.sub(r'<.*>', '', msg.get("From", "")).strip().strip('"')
                confirmations.append({
                    "company": company,
                    "subject": msg.get("Subject", "")[:80],
                    "date": msg.get("Date", ""),
                })

        conn.logout()

        result = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "count": len(confirmations),
            "companies": confirmations,
        }

        # Save to file
        os.makedirs(CONFIRMATIONS_FILE.parent, exist_ok=True)
        history = json.loads(CONFIRMATIONS_FILE.read_text()) if CONFIRMATIONS_FILE.exists() else []
        history.append(result)
        # Keep last 30 days
        history = history[-30:]
        CONFIRMATIONS_FILE.write_text(json.dumps(history, indent=2))

        print(f"📧 Application confirmations (last {days_back} day): {len(confirmations)}")
        for c in confirmations[:10]:
            print(f"  ✅ {c['company']}: {c['subject'][:50]}")

        return result

    except Exception as e:
        print(f"❌ Confirmation check failed: {str(e)[:60]}")
        return {"count": 0, "companies": []}


if __name__ == "__main__":
    count_confirmations(days_back=1)
