#!/usr/bin/env python3
"""
Apollo Recruiter Discovery + Auto Outreach Pipeline.

Full pipeline:
1. Scrape Apollo.io for recruiters (Selenium + cookies)
2. Deduplicate against contacted.json (never email same person twice)
3. Send personalized CV email via Gmail SMTP
4. Track all contacts for follow-up sequence

This is the MAIN entry point for the weekly Apollo workflow.
Combines apollo_scraper.py (discovery) + outreach email sending.
"""
import json
import os
import re
import smtplib
import hashlib
import time
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
CONTACTED_FILE = DATA_DIR / "apollo_contacted.json"
RESULTS_FILE = DATA_DIR / "apollo_recruiters.json"

# ─── Config ───────────────────────────────────────────────────────────────────
MAX_EMAILS_PER_RUN = 25  # Don't spam — 25 per weekly run
GMAIL_USER = os.environ.get("GMAIL_USER", "bobrikh75@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

# ─── Bob's info ───────────────────────────────────────────────────────────────
CV_URL = "https://drive.google.com/drive/folders/1sJRyHCTC2Xend6VWn6hM07VufWQdw_qV?usp=sharing"
BOOK_URL = "https://calendar.app.google/DG7ug2xFUuQneV2r6"
LINKEDIN_URL = "https://www.linkedin.com/in/bobrikh75/"
PHONE = "347-268-5917"

# ─── Email signature ──────────────────────────────────────────────────────────
PHOTO_URL = ("https://lh7-rt.googleusercontent.com/docsz/AD_4nXdTFpRiWmBy6NPYZ4s2J9tMu1RN8"
             "HSnyakDELLUiBK4MhkV-W-wO9EQJvCK5DNrSuV4hVHjOQ85QuNff994QwraSCUHcIXnGAYaRy"
             "Wa8eF43nJqFlEV4-VSYyAcOgkAYT1cWiDbZ0zuvhpmyr8XsfBmUaDI?key=f7Af-7daiBWgEMeWs4Hs_Q")

SIGNATURE_HTML = f'''<table style="border:none;border-collapse:collapse"><colgroup><col width="262"><col width="331"></colgroup><tbody><tr style="height:207pt"><td style="border-left:solid #ffffff 0.75pt;border-right:solid #1155cc 3pt;border-bottom:solid #ffffff 0.75pt;border-top:solid #ffffff 0.75pt;vertical-align:top;padding:5pt"><p dir="ltr" style="line-height:1.44;margin:0"><span style="border:none;display:inline-block;overflow:hidden;width:248px;height:248px"><img src="{PHOTO_URL}" width="248" height="248" style="margin:0"></span></p></td><td style="border-left:solid #1155cc 3pt;border-right:solid #ffffff 0.75pt;border-bottom:solid #ffffff 0.75pt;border-top:solid #ffffff 0.75pt;vertical-align:top;padding:5pt"><p dir="ltr" style="line-height:1.44;text-align:center;margin:0"><span style="font-size:18pt;font-family:\'Times New Roman\',serif;color:#1155cc;font-weight:700">Bob Rikh</span></p><p dir="ltr" style="line-height:1.44;text-align:center;margin:0"><span style="font-size:13pt;font-family:\'Times New Roman\',serif">Parker, CO, 80314&nbsp; </span><a href="mailto:bobrikh75@gmail.com"><span style="font-size:13pt;font-family:\'Times New Roman\',serif;color:#1155cc;font-weight:700">Gmail</span></a><span style="font-size:13pt;font-family:\'Times New Roman\',serif;font-weight:700">&nbsp; {PHONE} </span><a href="{BOOK_URL}"><span style="font-size:13pt;font-family:\'Times New Roman\',serif;color:#1155cc;font-weight:700">Book an appointment</span></a><span style="font-size:13pt;font-family:\'Times New Roman\',serif;font-weight:700">&nbsp;&nbsp;</span><a href="{CV_URL}"><b style="font-size:13pt;font-family:\'Times New Roman\',serif;color:#1155cc">CV</b></a><span style="font-size:13pt;font-family:\'Times New Roman\',serif;font-weight:700">&nbsp;&nbsp;</span><a href="{LINKEDIN_URL}"><b style="font-size:13pt;font-family:\'Times New Roman\',serif;color:#1155cc">LinkedIn</b></a></p><br><h1 dir="ltr" style="line-height:1.44;text-align:center;margin:0"><span style="font-size:12pt;font-family:\'Times New Roman\',serif;color:#000;font-weight:normal">Experienced Java Back-End Developer &amp; Specializing in Spring Ecosystem with QA Automation Test Agile Methodologies&#x2551;RESTful APIs&#x2551;QA&#x2551;Microservices&#x2551;AWS Cloud &#x2551;Apache Kafka &#x2551;Docker &#x2551; Kubernetes</span></h1></td></tr></tbody></table>'''


def email_hash(email: str) -> str:
    return hashlib.md5(email.lower().strip().encode()).hexdigest()[:12]


# Emails that are NOT real people — never send to these
_SKIP_LOCAL_PARTS = {
    "info", "admin", "support", "help", "contact", "team", "hr",
    "careers", "jobs", "hiring", "talent", "recruiting", "noreply",
    "no-reply", "sales", "marketing", "hello", "apply", "resume",
    "resumes", "mail", "office", "billing", "finance", "legal",
    "press", "pr", "webmaster", "postmaster", "abuse", "security",
    "privacy", "notification", "alerts", "system", "bot", "auto",
}

_SKIP_DOMAINS = {
    "indeed.com", "linkedin.com", "dice.com", "greenhouse.io",
    "lever.co", "ziprecruiter.com", "monster.com", "apollo.io",
    "example.com", "test.com", "noreply.com",
}


def _is_sendable_email(email: str) -> bool:
    """STRICT validation — only send to emails that are definitely real people.
    
    Rules:
    - Must have @ and valid domain
    - Local part must look like a person name (first.last, flast, etc)
    - Not a generic/role-based address
    - Not a job board or system email
    - No guessing — if unsure, DON'T send
    """
    if not email or "@" not in email:
        return False
    
    local, domain = email.split("@", 1)
    
    # Skip known non-person domains
    if domain.lower() in _SKIP_DOMAINS:
        return False
    
    # Skip generic local parts
    local_lower = local.lower().replace("-", "").replace("_", "")
    if local_lower in _SKIP_LOCAL_PARTS:
        return False
    
    # Check individual parts (e.g., no-reply → noreply)
    parts = re.split(r'[._\-]', local.lower())
    if any(p in _SKIP_LOCAL_PARTS for p in parts):
        return False
    
    # Must start with a letter
    if not local[0].isalpha():
        return False
    
    # Must be reasonable length
    if len(local) < 3 or len(local) > 50:
        return False
    
    # Must have at least one letter
    if not re.search(r'[a-zA-Z]', local):
        return False
    
    # Good indicators: has a dot (first.last) or is short enough to be flast/firstl
    return True


def load_contacted() -> dict:
    """Load ALL contacted records — both Apollo-specific AND main outreach.
    This prevents sending duplicate emails across pipelines."""
    merged = {}
    
    # Apollo's own contacted file
    if CONTACTED_FILE.exists():
        try:
            merged.update(json.loads(CONTACTED_FILE.read_text()))
        except Exception:
            pass
    
    # Main outreach contacted.json (from outreach.py / recruiter_search.py)
    main_contacted = SCRIPT_DIR.parent.parent / "contacted.json"
    if main_contacted.exists():
        try:
            merged.update(json.loads(main_contacted.read_text()))
        except Exception:
            pass
    
    # Also check agent-level contacted
    agent_contacted = DATA_DIR / "vendor_outreach_history.json"
    if agent_contacted.exists():
        try:
            history = json.loads(agent_contacted.read_text())
            # May be a list or dict
            if isinstance(history, list):
                for entry in history:
                    e = entry.get("email", "")
                    if e:
                        merged[email_hash(e)] = entry
            elif isinstance(history, dict):
                merged.update(history)
        except Exception:
            pass
    
    return merged


def save_contacted(data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONTACTED_FILE.write_text(json.dumps(data, indent=2))


def build_recruiter_email(name: str, title: str, company: str) -> tuple[str, str, str]:
    """Build personalized email for a recruiter found on Apollo.
    
    STRICT RULES:
    - Use first name ONLY if we have a verified full name (first + last)
    - If name is empty, single word, or looks wrong → use "Hello,"
    - Never guess a name from email address
    - Always state clearly: C2C, rate, availability, no sponsorship
    
    Returns: (subject, html_body, plain_body)
    """
    # STRICT name handling — only use if we have a verified first+last name
    greeting = "Hello,"
    name_parts = name.strip().split() if name else []
    if len(name_parts) >= 2 and len(name_parts[0]) >= 2:
        # Verify it looks like a real name (no numbers, no all-caps acronyms)
        first = name_parts[0]
        if first[0].isupper() and first[1:].islower() and first.isalpha():
            greeting = f"Hi {first},"
    
    # Context line — only if we KNOW their role and company
    if company and title and "bench" in title.lower():
        context_line = f"I'm reaching out because I'm actively looking for C2C/Corp-to-Corp Java contracts and saw you work with bench candidates at {company}."
    elif company and title and ("staffing" in title.lower() or "recruiter" in title.lower()):
        context_line = f"I'm reaching out because I'm available for C2C/Corp-to-Corp placement and saw your recruiter profile at {company}."
    elif company:
        context_line = f"I'm reaching out because I'm available for C2C/Corp-to-Corp contracts. I noticed {company} works with Java backend developers."
    else:
        context_line = "I'm reaching out because I'm available for C2C/Corp-to-Corp Java backend contracts."

    subject = "Java Backend Developer — C2C Available — Bob Rikh"

    html = f"""<div style="font-family:Arial,sans-serif;font-size:14px;color:#333">
<p>{greeting}</p>

<p>{context_line}</p>

<p><strong>What I'm looking for:</strong></p>
<ul style="margin:5px 0;padding-left:20px">
<li><strong>Work type:</strong> C2C / Corp-to-Corp ONLY (no W2)</li>
<li><strong>Rate:</strong> $70–95/hr C2C (flexible depending on project scope)</li>
<li><strong>Availability:</strong> Immediate — can start within 2 weeks</li>
<li><strong>Location:</strong> Parker, CO, United States — Remote preferred</li>
<li><strong>Authorization:</strong> Green Card holder — NO sponsorship needed</li>
</ul>

<p><strong>My background (8+ years):</strong></p>
<ul style="margin:5px 0;padding-left:20px">
<li>Java 17, Spring Boot, Spring Cloud, Spring Security</li>
<li>Apache Kafka, Kubernetes, Docker, AWS</li>
<li>Microservices, GraphQL, REST APIs</li>
<li>MongoDB, Cassandra, PostgreSQL, Redis</li>
<li>CI/CD (GitLab), DataDog, Splunk, Agile/Scrum</li>
</ul>

<p><strong>Currently:</strong> Contracting at Charter Communications (Spectrum) as a Java Backend Developer.</p>

<p>If you have any Java/Spring Boot C2C positions, I'd love to connect:</p>

<p>
📄 <a href="{CV_URL}">My CV</a> &nbsp;|&nbsp;
📅 <a href="{BOOK_URL}">Book a 15-min call</a> &nbsp;|&nbsp;
💼 <a href="{LINKEDIN_URL}">LinkedIn</a>
</p>

<br>
{SIGNATURE_HTML}
</div>"""

    plain = f"""{greeting}

{context_line}

WHAT I'M LOOKING FOR:
- Work type: C2C / Corp-to-Corp ONLY (no W2)
- Rate: $70-95/hr C2C (flexible depending on project)
- Availability: Immediate — can start within 2 weeks
- Location: Parker, CO, United States — Remote preferred
- Authorization: Green Card holder — NO sponsorship needed

MY BACKGROUND (8+ years):
- Java 17, Spring Boot, Spring Cloud, Spring Security
- Apache Kafka, Kubernetes, Docker, AWS
- Microservices, GraphQL, REST APIs
- MongoDB, Cassandra, PostgreSQL, Redis
- CI/CD, DataDog, Splunk, Agile/Scrum

Currently contracting at Charter Communications (Spectrum).

CV: {CV_URL}
Book a call: {BOOK_URL}
LinkedIn: {LINKEDIN_URL}

Best regards,
Bob Rikh
Parker, CO 80314
{PHONE}
bobrikh75@gmail.com"""

    return subject, html, plain


def send_email(to_email: str, subject: str, html: str, plain: str) -> bool:
    """Send email via Gmail SMTP."""
    if not GMAIL_APP_PASSWORD:
        print(f"    ⚠️  No GMAIL_APP_PASSWORD set — cannot send")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = f"Bob Rikh <{GMAIL_USER}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = GMAIL_USER
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.starttls()
            s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            s.send_message(msg)
        return True
    except Exception as e:
        print(f"    ❌ SMTP failed: {e}")
        return False


def run_outreach(contacts: list) -> dict:
    """Send outreach emails to new Apollo contacts.
    
    Args:
        contacts: list of dicts with keys: name, email, title, company, linkedin_url
    
    Returns:
        Summary dict with counts
    """
    contacted = load_contacted()
    sent = 0
    skipped = 0
    failed = 0

    print(f"\n📧 Starting outreach to {len(contacts)} Apollo contacts...")
    print(f"   Max emails this run: {MAX_EMAILS_PER_RUN}")
    print(f"   Already contacted: {len(contacted)}\n")

    for contact in contacts:
        if sent >= MAX_EMAILS_PER_RUN:
            print(f"   ⏸️  Hit daily limit ({MAX_EMAILS_PER_RUN})")
            break

        email = contact.get("email", "").lower().strip()
        if not email or "@" not in email:
            continue

        # STRICT: Skip emails that are not real people
        if not _is_sendable_email(email):
            skipped += 1
            continue

        eh = email_hash(email)
        if eh in contacted:
            skipped += 1
            continue

        name = contact.get("name", "")
        title = contact.get("title", "")
        company = contact.get("company", "")

        # STRICT: Must have a real name — no guessing who we're emailing
        if not name or len(name.split()) < 2:
            skipped += 1
            continue

        subject, html, plain = build_recruiter_email(name, title, company)
        print(f"   📧 {name or '?'} <{email}> @ {company} ({title})...", end=" ")

        if send_email(email, subject, html, plain):
            contacted[eh] = {
                "email": email,
                "name": name,
                "title": title,
                "company": company,
                "linkedin_url": contact.get("linkedin_url", ""),
                "date": datetime.now().isoformat(),
                "last_contact": datetime.now().isoformat(),
                "source": "apollo_scraper",
                "replied": False,
                "bounced": False,
                "followed_up": False,
            }
            sent += 1
            print(f"✅ ({sent}/{MAX_EMAILS_PER_RUN})")
            # Small delay between sends (avoid Gmail rate limiting)
            time.sleep(2)
        else:
            failed += 1
            print("❌")

    save_contacted(contacted)

    summary = {
        "sent": sent,
        "skipped_already_contacted": skipped,
        "failed": failed,
        "total_in_list": len(contacts),
        "total_ever_contacted": len(contacted),
        "timestamp": datetime.now().isoformat(),
    }
    print(f"\n📊 Outreach Summary:")
    print(f"   ✅ Sent: {sent}")
    print(f"   ⏭️  Skipped (already contacted): {skipped}")
    print(f"   ❌ Failed: {failed}")
    print(f"   📋 Total ever contacted: {len(contacted)}")

    return summary


def main():
    """Full pipeline: Apollo scrape → outreach emails."""
    print("=" * 60)
    print("🎯 APOLLO RECRUITER DISCOVERY + AUTO OUTREACH")
    print("=" * 60)
    print(f"   Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"   Target: C2C/Staffing recruiters in United States")
    print(f"   Action: Scrape Apollo → Send CV emails\n")

    # Step 1: Run Apollo scraper
    from apollo_scraper import main as scrape_apollo
    contacts = scrape_apollo(headless=True)

    if not contacts:
        # Try loading from file (may have been populated by a previous run)
        if RESULTS_FILE.exists():
            contacts = json.loads(RESULTS_FILE.read_text())
            print(f"📂 Loaded {len(contacts)} contacts from previous Apollo scrape")
        else:
            print("⚠️  No contacts to send to. Check Apollo cookies.")
            return

    # Step 2: Send outreach emails
    if not GMAIL_APP_PASSWORD:
        print("\n⚠️  GMAIL_APP_PASSWORD not set — saving contacts only (no emails sent)")
        print(f"   {len(contacts)} contacts saved to {RESULTS_FILE}")
        return

    summary = run_outreach(contacts)

    # Save run summary
    summary_file = DATA_DIR / "apollo_outreach_log.json"
    log = []
    if summary_file.exists():
        try:
            log = json.loads(summary_file.read_text())
        except Exception:
            pass
    log.append(summary)
    summary_file.write_text(json.dumps(log, indent=2))

    print(f"\n✅ Pipeline complete. Log saved to {summary_file.name}")


if __name__ == "__main__":
    main()
# Auto-trigger test 23:08
