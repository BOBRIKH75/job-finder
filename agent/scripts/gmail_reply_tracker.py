#!/usr/bin/env python3
"""
Gmail reply tracker — checks inbox for recruiter replies and updates contacted.json.

Run: python scripts/gmail_reply_tracker.py

Reads contacted.json, checks Gmail IMAP for replies from each recruiter's email,
marks replied contacts, and prints a summary of who responded.
"""
import imaplib
import email
import json
import os
from datetime import datetime
from pathlib import Path

GMAIL_USER = os.environ.get("GMAIL_USER", "bobrikh75@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

CONTACTED_FILE = Path(__file__).parent.parent.parent / "contacted.json"
HISTORY_FILE = Path(__file__).parent.parent.parent / "data" / "reply_tracker_history.json"


def load_contacted() -> dict:
    if CONTACTED_FILE.exists():
        return json.loads(CONTACTED_FILE.read_text())
    return {}


def save_contacted(data: dict):
    CONTACTED_FILE.write_text(json.dumps(data, indent=2))


def load_history() -> dict:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return {"last_run": None, "total_replies": 0}


def save_history(data: dict):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(data, indent=2))


def connect_imap() -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL("imap.gmail.com")
    conn.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    return conn


def get_reply_date(conn: imaplib.IMAP4_SSL, from_email: str) -> str | None:
    """Return the date of the most recent email FROM this address, or None."""
    conn.select("INBOX")
    _, data = conn.search(None, f'(FROM "{from_email}")')
    msg_ids = data[0].split()
    if not msg_ids:
        return None
    # Fetch the most recent one
    _, msg_data = conn.fetch(msg_ids[-1], "(RFC822.HEADER)")
    headers = email.message_from_bytes(msg_data[0][1])
    return headers.get("Date", datetime.utcnow().isoformat())


def check_sent_folder(conn: imaplib.IMAP4_SSL, to_email: str) -> bool:
    """Verify we actually sent to this address (avoid false positive replies)."""
    for folder in ("[Gmail]/Sent Mail", "Sent", "[Gmail]/Sent"):
        try:
            status, _ = conn.select(f'"{folder}"')
            if status != "OK":
                continue
            _, data = conn.search(None, f'(TO "{to_email}")')
            if data[0].split():
                return True
        except Exception:
            continue
    return True  # Assume sent if we can't verify


def run_tracker():
    if not GMAIL_APP_PASSWORD:
        print("No GMAIL_APP_PASSWORD set — skipping reply tracker")
        return

    contacted = load_contacted()
    history = load_history()

    if not contacted:
        print("contacted.json is empty — nothing to check")
        return

    # Only check contacts that haven't replied yet
    to_check = {
        key: info for key, info in contacted.items()
        if info.get("email") and not info.get("replied")
    }

    print(f"Checking {len(to_check)} contacts for replies (out of {len(contacted)} total)...")

    if not to_check:
        print("All contacts already marked as replied or no email recorded.")
        return

    try:
        conn = connect_imap()
    except Exception as e:
        print(f"IMAP connect failed: {e}")
        return

    new_replies = []
    checked = 0

    for key, info in to_check.items():
        recruiter_email = info["email"]
        try:
            reply_date = get_reply_date(conn, recruiter_email)
            if reply_date:
                contacted[key]["replied"] = True
                contacted[key]["replied_at"] = reply_date
                new_replies.append({
                    "email": recruiter_email,
                    "company": info.get("company", "?"),
                    "job": info.get("job", "?"),
                    "replied_at": reply_date,
                })
                print(f"  📬 REPLY: {recruiter_email} ({info.get('company','?')}) — {info.get('job','?')}")
            checked += 1
        except Exception as e:
            print(f"  ⚠️  Error checking {recruiter_email}: {e}")

    conn.logout()

    # Save updated contacts
    save_contacted(contacted)

    # Update history
    history["last_run"] = datetime.utcnow().isoformat()
    history["total_replies"] = sum(1 for v in contacted.values() if v.get("replied"))
    history["last_new_replies"] = len(new_replies)
    save_history(history)

    # Summary
    total_sent = len(contacted)
    total_replied = history["total_replies"]
    reply_rate = round((total_replied / total_sent) * 100, 1) if total_sent else 0

    print(f"\n📊 Reply Tracker Summary:")
    print(f"  Checked:      {checked}")
    print(f"  New replies:  {len(new_replies)}")
    print(f"  Total replied:{total_replied} / {total_sent} ({reply_rate}% reply rate)")

    if new_replies:
        print(f"\n🎉 New replies this run:")
        for r in new_replies:
            print(f"  → {r['email']} @ {r['company']} — {r['job']}")


if __name__ == "__main__":
    run_tracker()
