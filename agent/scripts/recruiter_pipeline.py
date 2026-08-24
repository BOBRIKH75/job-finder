#!/usr/bin/env python3
"""
Recruiter Pipeline Tracker — tracks each recruiter conversation through stages.

Stages: CONTACTED → REPLIED → SCREENING → SCHEDULED → INTERVIEWED → OFFERED → HIRED
Auto-detects stage changes by scanning Gmail for keywords.
Sends follow-up if recruiter goes silent for 3 days after our reply.

Run: python agent/scripts/recruiter_pipeline.py
"""
import imaplib
import email
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

GMAIL_USER = os.environ.get("GMAIL_USER", "bobrikh75@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
RESEND_KEY = os.environ.get("RESEND_KEY", "")

PIPELINE_FILE = Path(__file__).parent.parent / "data" / "recruiter_pipeline.json"

STAGES = ["contacted", "replied", "screening", "scheduled", "interviewed", "offered", "hired", "dead"]

# Keywords to detect stage transitions from email content
STAGE_SIGNALS = {
    "scheduled": ["calendar", "booked", "confirmed", "meeting", "scheduled", "invite", 
                  "zoom link", "teams link", "google meet", "interview on"],
    "screening": ["phone screen", "quick call", "initial call", "30 min", "15 min",
                  "let's chat", "tell me about", "walk me through"],
    "interviewed": ["next steps", "panel", "final round", "onsite", "technical interview",
                    "coding challenge", "take-home", "assessment"],
    "offered": ["offer", "compensation", "salary", "start date", "background check",
                "congratulations", "pleased to offer"],
    "dead": ["unfortunately", "not moving forward", "decided to go", "position filled",
             "no longer", "not a fit", "pursuing other candidates"],
}

FOLLOW_UP_DAYS = 3
MAX_FOLLOW_UPS = 2
FOLLOW_UP_TEMPLATE = """Hi {name},

Just following up on my previous message. I'm still very interested in the {role} opportunity and available to chat at your convenience.

You can book a time here: https://calendar.google.com/calendar/u/0/appointments/AcZssZ22KPDPginBf34kMvb6wAFQUEHtG5sJ3PF_1k8=

Best regards,
Bob Rikh
347-268-5917"""


def load_pipeline() -> dict:
    """Load pipeline state."""
    if PIPELINE_FILE.exists():
        return json.loads(PIPELINE_FILE.read_text())
    return {"recruiters": {}, "stats": {}, "last_updated": ""}


def save_pipeline(data: dict):
    """Save pipeline state."""
    data["last_updated"] = datetime.now().isoformat()
    os.makedirs(PIPELINE_FILE.parent, exist_ok=True)
    PIPELINE_FILE.write_text(json.dumps(data, indent=2))


def detect_stage(subject: str, body: str) -> Optional[str]:
    """Detect pipeline stage from email content."""
    text = (subject + " " + body[:500]).lower()
    for stage, signals in STAGE_SIGNALS.items():
        if any(s in text for s in signals):
            return stage
    return None


def scan_inbox(pipeline: dict, days_back: int = 3) -> int:
    """Scan Gmail for stage transitions and new recruiter contacts."""
    if not GMAIL_APP_PASSWORD:
        print("⚠️ GMAIL_APP_PASSWORD not set")
        return 0

    updates = 0
    try:
        conn = imaplib.IMAP4_SSL("imap.gmail.com")
        conn.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        conn.select("INBOX")

        since_date = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
        _, msg_nums = conn.search(None, f'(SINCE "{since_date}")')

        for num in msg_nums[0].split():
            try:
                _, data = conn.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(data[0][1])

                sender_raw = msg.get("From", "")
                sender_email = re.search(r'<(.+?)>', sender_raw)
                sender_email = sender_email.group(1) if sender_email else sender_raw
                sender_email = sender_email.lower().strip()
                sender_name = re.sub(r'<.*>', '', sender_raw).strip().strip('"')

                # Skip our own sent emails and system emails
                if GMAIL_USER in sender_email or "github" in sender_email or "resend" in sender_email:
                    continue

                subject = msg.get("Subject", "")
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            try:
                                body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                            except Exception:
                                pass
                            break
                else:
                    try:
                        body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                    except Exception:
                        pass

                # Detect stage
                new_stage = detect_stage(subject, body)
                if not new_stage:
                    new_stage = "replied"  # they replied = at least this stage

                # Update pipeline
                key = sender_email
                if key not in pipeline["recruiters"]:
                    pipeline["recruiters"][key] = {
                        "name": sender_name,
                        "email": sender_email,
                        "stage": "contacted",
                        "first_contact": datetime.now().isoformat(),
                        "last_activity": datetime.now().isoformat(),
                        "company": "",
                        "role": "",
                        "follow_ups_sent": 0,
                        "history": []
                    }

                rec = pipeline["recruiters"][key]
                current_idx = STAGES.index(rec["stage"]) if rec["stage"] in STAGES else 0
                new_idx = STAGES.index(new_stage) if new_stage in STAGES else 0

                # Only advance forward (except "dead" can override anything)
                if new_idx > current_idx or new_stage == "dead":
                    rec["stage"] = new_stage
                    rec["history"].append({
                        "stage": new_stage,
                        "date": datetime.now().isoformat(),
                        "subject": subject[:80]
                    })
                    updates += 1

                rec["last_activity"] = datetime.now().isoformat()
                rec["name"] = sender_name or rec["name"]

                # Try to extract role/company from subject
                if not rec["role"] and ("java" in subject.lower() or "developer" in subject.lower() or "engineer" in subject.lower()):
                    rec["role"] = subject[:60]

            except Exception:
                continue

        conn.logout()
    except Exception as e:
        print(f"❌ Inbox scan failed: {str(e)[:60]}")

    return updates


def send_follow_ups(pipeline: dict) -> int:
    """Send follow-up to recruiters who went silent after our reply."""
    if not RESEND_KEY:
        return 0

    import requests
    sent = 0
    now = datetime.now()

    for key, rec in pipeline["recruiters"].items():
        # Only follow up if: replied/screening stage + silent for 3+ days + < 2 follow-ups
        if rec["stage"] not in ("replied", "screening"):
            continue
        if rec["follow_ups_sent"] >= MAX_FOLLOW_UPS:
            continue

        last = datetime.fromisoformat(rec["last_activity"])
        if (now - last).days < FOLLOW_UP_DAYS:
            continue

        # Send follow-up
        name = rec["name"].split()[0] if rec["name"] else "there"
        role = rec["role"] or "the opportunity"
        body = FOLLOW_UP_TEMPLATE.format(name=name, role=role)

        try:
            resp = requests.post("https://api.resend.com/emails", json={
                "from": f"Bob Rikh <onboarding@resend.dev>",
                "to": [rec["email"]],
                "reply_to": GMAIL_USER,
                "subject": f"Following up - {role}",
                "text": body,
            }, headers={"Authorization": f"Bearer {RESEND_KEY}"}, timeout=15)

            if resp.status_code in (200, 201):
                rec["follow_ups_sent"] += 1
                rec["last_activity"] = now.isoformat()
                rec["history"].append({
                    "stage": "follow_up",
                    "date": now.isoformat(),
                    "subject": f"Follow-up #{rec['follow_ups_sent']}"
                })
                sent += 1
                print(f"  📤 Follow-up sent to {rec['name']} ({rec['email']})")
        except Exception:
            continue

    return sent


def print_summary(pipeline: dict):
    """Print pipeline summary."""
    stage_counts = {}
    for rec in pipeline["recruiters"].values():
        stage = rec["stage"]
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

    print(f"\n📊 Recruiter Pipeline ({len(pipeline['recruiters'])} total)")
    print(f"  {'Stage':<15} {'Count'}")
    print(f"  {'-'*25}")
    for stage in STAGES:
        count = stage_counts.get(stage, 0)
        if count > 0:
            emoji = {"contacted": "📧", "replied": "💬", "screening": "📞",
                     "scheduled": "📅", "interviewed": "🎯", "offered": "🎉",
                     "hired": "✅", "dead": "💀"}.get(stage, "•")
            print(f"  {emoji} {stage:<13} {count}")


if __name__ == "__main__":
    pipeline = load_pipeline()
    
    print("🔄 Scanning inbox for stage updates...")
    updates = scan_inbox(pipeline)
    print(f"  {updates} stage transitions detected")
    
    print("\n📤 Checking for silent recruiters...")
    follow_ups = send_follow_ups(pipeline)
    print(f"  {follow_ups} follow-ups sent")
    
    print_summary(pipeline)
    save_pipeline(pipeline)
