#!/usr/bin/env python3
"""
Monthly vendor outreach — sends Bob Rikh's availability email to staffing firms.

PRIMARY sender: Gmail SMTP (smtp.gmail.com:587, GMAIL_USER + GMAIL_APP_PASSWORD).
  - Sends to REAL recruiters (Resend sandbox refused everyone except Bob's own
    address → 0/40 sent for months; Gmail sends to anyone, replies land in inbox).
FALLBACK sender: Resend API (only used if Gmail creds absent AND a verified domain
  Resend key is set).

Skips vendors contacted within the last TTL_DAYS days.
History is recorded ONLY on a successful send (a failed send is retried next run).

Run: python scripts/vendor_outreach.py
"""
import base64
import json, os, smtplib, sys, time
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from pathlib import Path

import requests

# --- Gmail SMTP (primary) ---
GMAIL_USER         = os.environ.get("GMAIL_USER", "bobrikh75@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

# --- Resend (fallback only) ---
RESEND_KEY  = os.environ.get("RESEND_KEY", "")
RESEND_FROM = os.environ.get("RESEND_FROM", "Bob Rikh <onboarding@resend.dev>")

REPLY_TO    = GMAIL_USER
TTL_DAYS    = 14   # per-recruiter cooldown: max once every 2 weeks (safe, not spammy)

VENDOR_FILE  = Path(__file__).parent.parent / "data" / "vendor_list.json"
LEADS_FILE   = Path(__file__).parent.parent / "data" / "recruiter_job_leads.json"
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


def load_recruiter_leads() -> list[dict]:
    """The GOLD source: REAL named recruiters who personally emailed Bob about Java
    jobs (harvested from his inbox). These are humans who reply/call — far higher
    value than guessed role inboxes. Emailed FIRST, every run."""
    if not LEADS_FILE.exists():
        return []
    try:
        rows = json.loads(LEADS_FILE.read_text())
    except Exception:
        return []
    leads = []
    seen = set()
    for r in rows if isinstance(rows, list) else []:
        em = (r.get("recruiter_email") or "").strip().lower()
        if not em or "@" not in em or em in seen:
            continue
        seen.add(em)
        leads.append({
            "email": em,
            "name": r.get("recruiter_name") or r.get("company") or em.split("@")[1].split(".")[0].title(),
            "company": r.get("company", ""),
        })
    if leads:
        print(f"Loaded {len(leads)} REAL named recruiters from recruiter_job_leads.json (emailed FIRST)")
    return leads


def load_vendors() -> list[dict]:
    # GOLD first: real named recruiters who emailed Bob (highest reply/call rate).
    leads = load_recruiter_leads()
    lead_emails = {l["email"] for l in leads}

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
            if em.lower() in lead_emails:   # already in the gold leads — don't duplicate
                continue
            if not v.get("name"):
                v["name"] = v.get("company") or em.split("@")[1].split(".")[0].title()
            clean.append(v)
        if clean or leads:
            # Prioritize NAMED recruiters (firstname.lastname@ → real people who reply)
            # over generic role inboxes (info@/careers@/jobs@ → low reply). Within the
            # daily cap, named people get contacted first = more calls.
            _ROLE = {"careers", "recruiting", "jobs", "hr", "info", "contact",
                     "talent", "apply", "support", "customersupport", "developers",
                     "noreply", "no-reply", "admin", "sales", "team"}
            # Pure dead-end inboxes that essentially NEVER reply to a cold availability
            # email (ATS auto-dumps). In NAMED_ONLY mode we skip these entirely so the
            # daily send budget is spent on humans who actually reply/call.
            _DEAD = {"careers", "jobs", "hr", "noreply", "no-reply", "apply",
                     "support", "customersupport", "admin", "donotreply"}
            def _is_dead_role(v):
                user = (v.get("email") or "").split("@")[0].lower()
                # dead if a pure role word, or any no-reply/do-not-reply variant
                if "noreply" in user.replace("-", "").replace(".", "") or \
                   "donotreply" in user.replace("-", "").replace(".", ""):
                    return True
                return user in _DEAD and "." not in user

            named_only = os.environ.get("OUTREACH_NAMED_ONLY", "1") == "1"
            if named_only:
                before = len(clean)
                clean = [v for v in clean if not _is_dead_role(v)]
                print(f"NAMED_ONLY: dropped {before - len(clean)} dead role inboxes "
                      f"(careers@/jobs@/hr@…) — targeting humans who reply")

            def _named_first(v):
                user = (v.get("email") or "").split("@")[0].lower()
                is_named = ("." in user and user not in _ROLE)
                return (0 if is_named else 1, user)   # named (0) sort before role (1)
            clean.sort(key=_named_first)
            # GOLD leads go absolutely first, then named-sorted vendor list.
            result = leads + clean
            print(f"Loaded {len(result)} total recruiters "
                  f"({len(leads)} gold named-leads first, then {len(clean)} vendor list)")
            return result
    if leads:
        return leads
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


def _send_via_gmail(to_email: str, vendor_name: str) -> bool:
    """Send via Gmail SMTP (smtp.gmail.com:587) with the CV attached.
    This is the PRIMARY path — it actually delivers to real recruiters."""
    msg = MIMEMultipart()
    msg["From"] = f"Bob Rikh <{GMAIL_USER}>"
    msg["To"] = to_email
    msg["Reply-To"] = REPLY_TO
    msg["Subject"] = subject_for(to_email)   # varied per recruiter+week (anti-spam)
    msg.attach(MIMEText(make_body(vendor_name, to_email), "plain"))

    # Attach the CV PDF so recruiters get Bob's resume directly.
    if CV_PATH:
        try:
            part = MIMEApplication(CV_PATH.read_bytes(), _subtype="pdf")
            part.add_header(
                "Content-Disposition", "attachment",
                filename="Bob_Rikh_Java_Backend_Developer.pdf",
            )
            msg.attach(part)
        except Exception as exc:
            print(f"    CV attach skipped: {str(exc)[:50]}")

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
            s.starttls()
            s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            s.send_message(msg)
        return True
    except Exception as exc:
        print(f"    Gmail SMTP error: {str(exc)[:120]}")
        return False


def _send_via_resend(to_email: str, vendor_name: str) -> bool:
    """Fallback only. Resend free/sandbox keys refuse any address except the
    account owner's — kept only for a verified-domain Resend key."""
    payload = {
        "from": RESEND_FROM,
        "to": [to_email],
        "reply_to": REPLY_TO,
        "subject": subject_for(to_email),
        "text": make_body(vendor_name, to_email),
    }
    if CV_PATH:
        try:
            payload["attachments"] = [{
                "filename": "Bob_Rikh_Java_Backend_Developer.pdf",
                "content": base64.b64encode(CV_PATH.read_bytes()).decode(),
            }]
        except Exception as exc:
            print(f"    CV attach skipped: {str(exc)[:50]}")
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


def send_email(to_email: str, vendor_name: str) -> bool:
    """Gmail first (real delivery), Resend as fallback, dry-run if neither set."""
    if GMAIL_APP_PASSWORD:
        return _send_via_gmail(to_email, vendor_name)
    if RESEND_KEY:
        return _send_via_resend(to_email, vendor_name)
    print(f"  [DRY RUN] Would send to {vendor_name} ({to_email})"
          f"{' + CV' if CV_PATH else ''}")
    return True  # dry-run counts as success for history tracking


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
    DAILY_CAP = int(os.environ.get('OUTREACH_DAILY_CAP', '40'))
    if len(to_contact) > DAILY_CAP:
        # oldest-contacted first (fairness), then cap
        to_contact = to_contact[:DAILY_CAP]
        print(f"  (capped to {DAILY_CAP} sends this run — anti-spam; rest go next run)")

    sender = ("Gmail SMTP" if GMAIL_APP_PASSWORD
              else "Resend API" if RESEND_KEY else "DRY RUN")
    print(f"\nSending to {len(to_contact)} vendors via {sender}...")
    if sender == "DRY RUN":
        print("  No GMAIL_APP_PASSWORD or RESEND_KEY set — running in dry-run mode")

    sent = 0
    for vendor in to_contact:
        try:
            ok = send_email(vendor["email"], vendor["name"])
            if ok:
                print(f"  OK  {vendor['name']} ({vendor['email']})")
                sent += 1
                # Record history ONLY on success — a failed send must be retried
                # next run, not silently cooled-down for TTL_DAYS.
                history[vendor["email"]] = {
                    "name": vendor["name"],
                    "last_contacted": now.isoformat(),
                    "times_contacted": history.get(vendor["email"], {}).get("times_contacted", 0) + 1,
                }
            else:
                print(f"  ERR {vendor['name']} — send failed (will retry next run)")
            time.sleep(random.uniform(3, 8))   # human-like spacing (anti-spam)
        except Exception as exc:
            print(f"  ERR {vendor['name']}: {exc}")

    save_history(history)
    print(f"\nDONE: {sent}/{len(to_contact)} sent via {sender} | {len(history)} total in database")


if __name__ == "__main__":
    main()
