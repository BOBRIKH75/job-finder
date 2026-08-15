#!/usr/bin/env python3
"""
Monthly vendor outreach — sends Bob Rikh's availability email to staffing firms.

Uses Resend API (better deliverability than raw Gmail SMTP).
Skips vendors contacted within the last 30 days.

Run: python scripts/vendor_outreach.py
"""
import json, os, sys, time
from datetime import datetime
from pathlib import Path

import requests

RESEND_KEY  = os.environ.get("RESEND_KEY", "")
REPLY_TO    = os.environ.get("GMAIL_USER", "bobrikh75@gmail.com")
RESEND_FROM = "Bob Rikh <onboarding@resend.dev>"
TTL_DAYS    = 30

VENDOR_FILE  = Path(__file__).parent.parent.parent / "data" / "vendor_list.json"
HISTORY_FILE = Path(__file__).parent.parent.parent / "data" / "vendor_outreach_history.json"

FALLBACK_VENDORS = [
    # Tier 1 — FAANG placement track (TEKsystems/Apex = Allegis Group, Amazon/Google/Microsoft)
    {"name": "TEKsystems",          "email": "careers@teksystems.com"},
    {"name": "Apex Systems",        "email": "apexsystems@apexsystems.com"},
    {"name": "Insight Global",      "email": "info@insightglobal.com"},
    {"name": "Kforce",              "email": "us_staffingsupport@kforce.com"},
    {"name": "Genesis10",           "email": "info@genesis10.com"},
    {"name": "Dexian",              "email": "info@dexian.com"},
    {"name": "Randstad Technologies","email": "info@randstadusa.com"},
    # Tier 2 — high C2C volume staffing firms
    {"name": "INSPYR Solutions",    "email": "info@inspyrsolutions.com"},
    {"name": "Motion Recruitment",  "email": "recruiting@motionrecruitment.com"},
    {"name": "Collabera",           "email": "careers@collabera.com"},
    {"name": "Mastech Digital",     "email": "careers@mastechdigital.com"},
    {"name": "Pyramid Consulting",  "email": "info@pyramidci.com"},
    {"name": "RIT Solutions",       "email": "info@ritsolutions.com"},
    {"name": "ConsultAdd",          "email": "careers@consultadd.com"},
    {"name": "Tier2Tek",            "email": "careers@tier2tek.com"},
    {"name": "TalentBurst",         "email": "info@talentburst.com"},
    {"name": "Diverse Lynx",        "email": "info@diverselynx.com"},
    {"name": "Vdart",               "email": "info@vdart.com"},
    {"name": "Skiltrek",            "email": "info@skiltrek.com"},
    {"name": "Modis (Adecco)",      "email": "modis@adeccousa.com"},
]

SUBJECT = "Senior Java/Spring Boot Dev — C2C Available, Green Card, Parker CO"

RESUME_LINK  = "https://drive.google.com/drive/folders/1sJRyHCTC2Xend6VWn6hM07VufWQdw_qV"
LINKEDIN_URL = "https://www.linkedin.com/in/bobrikh75/"


def make_body(vendor_name: str) -> str:
    return (
        f"Hi {vendor_name} team,\n\n"
        "I'm a Senior Java Backend Developer with 10+ years of experience, "
        "looking for C2C contract roles.\n\n"
        "Quick summary:\n"
        "  Java 17, Spring Boot, Microservices, Kafka, Kubernetes, Docker, AWS\n"
        "  10 years experience — enterprise scale (Charter Communications)\n"
        "  Green Card holder — no sponsorship needed, no restrictions\n"
        "  Rate: $70-90/hr C2C  |  Available: Immediately  |  Location: Parker CO (100% Remote)\n\n"
        f"Resume:   {RESUME_LINK}\n"
        f"LinkedIn: {LINKEDIN_URL}\n\n"
        "If you have Java or Spring Boot contract openings, I'd love to connect.\n\n"
        f"Bob Rikh\n"
        f"347-268-5917  |  {REPLY_TO}\n"
    )


def load_vendors() -> list[dict]:
    if VENDOR_FILE.exists():
        data = json.loads(VENDOR_FILE.read_text())
        vendors = data.get("vendors", [])
        if vendors:
            print(f"Loaded {len(vendors)} vendors from vendor_list.json")
            return vendors
    print(f"Using fallback vendor list ({len(FALLBACK_VENDORS)} firms)")
    return FALLBACK_VENDORS


def load_history() -> dict:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return {}


def save_history(history: dict):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, indent=2))


def should_contact(history: dict, email: str, now: datetime) -> tuple[bool, int]:
    entry = history.get(email, {})
    if not entry:
        return True, -1
    last = datetime.fromisoformat(entry["last_contacted"])
    days_ago = (now - last).days
    return days_ago >= TTL_DAYS, days_ago


def send_via_resend(to_email: str, vendor_name: str) -> bool:
    if not RESEND_KEY:
        print(f"  [DRY RUN] Would send to {vendor_name} ({to_email})")
        return True  # count as success for history tracking in dry-run
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "from": RESEND_FROM,
            "to": [to_email],
            "reply_to": REPLY_TO,
            "subject": SUBJECT,
            "text": make_body(vendor_name),
        },
        timeout=10,
    )
    if resp.status_code in (200, 201):
        return True
    print(f"    Resend API error: HTTP {resp.status_code} — {resp.text[:120]}")
    return False


def main():
    vendors = load_vendors()
    history = load_history()
    now = datetime.utcnow()

    to_contact = []
    for v in vendors:
        ok, days_ago = should_contact(history, v["email"], now)
        if ok:
            to_contact.append(v)
        else:
            print(f"  SKIP {v['name']} — contacted {days_ago}d ago (TTL={TTL_DAYS}d)")

    if not to_contact:
        print("All vendors contacted within TTL. Nothing to send.")
        return

    print(f"\nSending to {len(to_contact)} vendors via Resend API...")
    if not RESEND_KEY:
        print("  RESEND_KEY not set — running in dry-run mode")

    sent = 0
    for vendor in to_contact:
        try:
            ok = send_via_resend(vendor["email"], vendor["name"])
            if ok:
                print(f"  OK  {vendor['name']} ({vendor['email']})")
                sent += 1
            else:
                print(f"  ERR {vendor['name']} — send failed")
            history[vendor["email"]] = {
                "name": vendor["name"],
                "last_contacted": now.isoformat(),
                "times_contacted": history.get(vendor["email"], {}).get("times_contacted", 0) + 1,
            }
            time.sleep(1)
        except Exception as exc:
            print(f"  ERR {vendor['name']}: {exc}")

    save_history(history)
    print(f"\nDONE: {sent}/{len(to_contact)} sent | {len(history)} total in database")


if __name__ == "__main__":
    main()
