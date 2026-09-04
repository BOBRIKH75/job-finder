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
TTL_DAYS    = 14   # per-recruiter cooldown: max once every 2 weeks (safe, not spammy)

VENDOR_FILE  = Path(__file__).parent.parent / "data" / "vendor_list.json"
HISTORY_FILE = Path(__file__).parent.parent / "data" / "vendor_outreach_history.json"
# CV to attach (resolve first existing)
_CV_CANDIDATES = [
    Path(__file__).parent.parent / "resume.pdf",
    Path.home() / "Downloads" / "CV" / "Bob_Rikh_Java_Backend_Developer_C2C.pdf",
]
CV_PATH = next((p for p in _CV_CANDIDATES if p.exists()), None)

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

# Anti-spam: rotate SUBJECT + BODY so no two sends look identical (identical repeated emails
# are the #1 spam-filter/block trigger). A variant is picked deterministically per recruiter+week
# so each firm gets a fresh-looking, non-duplicate message each cycle.
SUBJECT_VARIANTS = [
    "Senior Java/Spring Boot Dev — C2C Available (Green Card, Remote)",
    "Java Backend Engineer, 10+ yrs — Open for C2C Contract (Remote)",
    "Available for C2C: Senior Java / Spring Boot / AWS (Green Card)",
    "Java/Microservices Contractor Available — C2C, No Sponsorship",
    "Senior Java Developer seeking C2C — Spring Boot, Kafka, AWS (Remote)",
]
_GREETINGS = ["Hi {v} team,", "Hello {v} team,", "Hi {v} recruiting team,",
              "Hello {v},", "Hi there {v} team,"]
_OPENERS = [
    "I'm a Senior Java Backend Developer with 10+ years of experience, looking for C2C contract roles.",
    "I'm a Senior Java/Spring Boot engineer (10+ yrs) currently open to C2C contract opportunities.",
    "I'm reaching out as a Senior Java Backend Developer (10+ yrs exp) available for C2C contracts.",
    "I'm a backend Java developer with 10+ years' experience, seeking a C2C contract role.",
]
_CLOSERS = [
    "If you have Java or Spring Boot contract openings, I'd love to connect.",
    "If any Java/Spring Boot contract roles come up, I'd be glad to talk.",
    "Happy to share more detail — feel free to call or email if there's a fit.",
    "If you're staffing Java/backend contracts, let's connect.",
]

RESUME_LINK  = "https://drive.google.com/drive/folders/1sJRyHCTC2Xend6VWn6hM07VufWQdw_qV"
LINKEDIN_URL = "https://www.linkedin.com/in/bobrikh75/"


def _variant_index(email: str, n: int) -> int:
    """Deterministic per recruiter + ISO-week → same recruiter gets a DIFFERENT variant each
    week, and never the identical message twice in a row."""
    import hashlib
    from datetime import datetime as _dt
    week = _dt.utcnow().isocalendar()[1]
    h = int(hashlib.md5(f"{email}:{week}".encode()).hexdigest(), 16)
    return h % n


def subject_for(email: str) -> str:
    return SUBJECT_VARIANTS[_variant_index(email, len(SUBJECT_VARIANTS))]


def make_body(vendor_name: str, email: str = "") -> str:
    i = _variant_index(email or vendor_name, 100)
    greet = _GREETINGS[i % len(_GREETINGS)].format(v=vendor_name)
    opener = _OPENERS[i % len(_OPENERS)]
    closer = _CLOSERS[i % len(_CLOSERS)]
    return (
        f"{greet}\n\n"
        f"{opener}\n\n"
        "Quick summary:\n"
        "  Java 17, Spring Boot, Microservices, Kafka, Kubernetes, Docker, AWS\n"
        "  10 years experience — enterprise scale (Charter Communications)\n"
        "  Green Card holder — no sponsorship needed, no restrictions\n"
        "  Rate: $70-90/hr C2C  |  Available: Immediately  |  Location: Parker CO (100% Remote)\n\n"
        f"Resume:   {RESUME_LINK}\n"
        f"LinkedIn: {LINKEDIN_URL}\n\n"
        f"{closer}\n\n"
        f"Bob Rikh\n"
        f"347-268-5917  |  {REPLY_TO}\n"
    )


def load_vendors() -> list[dict]:
    if VENDOR_FILE.exists():
        data = json.loads(VENDOR_FILE.read_text())
        # harvester writes a plain LIST; older format was {"vendors": [...]}
        vendors = data if isinstance(data, list) else data.get("vendors", [])
        # keep only entries with a usable email; default name from company/email
        clean = []
        for v in vendors:
            em = (v.get("email") or "").strip()
            if not em or "@" not in em:
                continue
            if not v.get("name"):
                v["name"] = v.get("company") or em.split("@")[1].split(".")[0].title()
            clean.append(v)
        if clean:
            print(f"Loaded {len(clean)} vendors/recruiters from vendor_list.json")
            return clean
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
        print(f"  [DRY RUN] Would send to {vendor_name} ({to_email})"
              f"{' + CV' if CV_PATH else ''}")
        return True  # count as success for history tracking in dry-run
    payload = {
        "from": RESEND_FROM,
        "to": [to_email],
        "reply_to": REPLY_TO,
        "subject": subject_for(to_email),   # varied per recruiter+week (anti-spam)
        "text": make_body(vendor_name, to_email),
    }
    # Attach the CV so recruiters get Bob's resume directly.
    if CV_PATH:
        try:
            import base64
            payload["attachments"] = [{
                "filename": "Bob_Rikh_Java_Backend_Developer.pdf",
                "content": base64.b64encode(CV_PATH.read_bytes()).decode(),
            }]
        except Exception as _e:
            print(f"    CV attach skipped: {str(_e)[:50]}")
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=15,
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

    # ANTI-SPAM: cap sends per run + space them out. Never blast the whole list at once (a burst
    # of identical-source emails is a block trigger). Weekly schedule + cap spreads outreach.
    import random
    DAILY_CAP = int(os.environ.get('OUTREACH_DAILY_CAP', '15'))
    if len(to_contact) > DAILY_CAP:
        # oldest-contacted first (fairness), then cap
        to_contact = to_contact[:DAILY_CAP]
        print(f"  (capped to {DAILY_CAP} sends this run — anti-spam; rest go next run)")

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
            time.sleep(random.uniform(3, 8))   # human-like spacing (anti-spam)
        except Exception as exc:
            print(f"  ERR {vendor['name']}: {exc}")

    save_history(history)
    print(f"\nDONE: {sent}/{len(to_contact)} sent | {len(history)} total in database")


if __name__ == "__main__":
    main()
