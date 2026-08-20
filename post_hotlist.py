#!/usr/bin/env python3
"""
Post Bob's C2C hotlist/availability to Google Groups daily.
Rotates groups so each one gets posted once per week (no spam).

Posts via Gmail SMTP → groupname@googlegroups.com

Schedule: runs daily, posts to ~6 groups per day (31 groups ÷ 5 weekdays)
"""

import os
import json
import smtplib
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, date
from pathlib import Path

GMAIL_USER = os.environ.get("GMAIL_USER", "bobrikh75@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# All C2C Google Groups (posting address = groupname@googlegroups.com)
ALL_GROUPS = [
    'c2chotlist-requirement-posting', 'only-c2c-req',
    'c2c-w2--requirements', 'C2C-Corp2Corp-Jobs', 'job-bank',
    'corp-2-corp', 'corp-to-corp-connection', 'c2c-requirements-usa',
    'c2c-corp-to-corp-remote-jobs', 'c2c-vendor-requirements',
    'hotlistreqs', 'javamug-jobs',
    'vendor-list-benchsales', 'corp2c-requriments',
    'pdusrecruiter', 'c2c-with-nexera-solutions',
    'c2crequirements4bench', 'c2c-requirements-on-daily-basis',
    'RajeshC2Crequirements', 'c2ctrinity', 'mahesh-c2c-Hotlists',
    'urgent-corp-to-corp-requirements', 'dcro',
    'us-it-staffing-c2c-requirements', 'c2c-daily-requirements-Imp',
    'whythiskolaverydi', 'sureshotjobs', 'SoftwareIT',
    'corp-to-corp-requirements22', 'therecruitmenthub',
    'android-app-develpoment',
]

GROUPS_PER_DAY = 6  # 31 groups ÷ 5 weekdays ≈ 6/day


def get_todays_groups() -> list[str]:
    """Rotate groups — different set each day, cycles through all."""
    day_of_year = date.today().timetuple().tm_yday
    start = (day_of_year * GROUPS_PER_DAY) % len(ALL_GROUPS)
    groups = []
    for i in range(GROUPS_PER_DAY):
        idx = (start + i) % len(ALL_GROUPS)
        groups.append(ALL_GROUPS[idx])
    return groups


def load_post_history() -> dict:
    """Track when we last posted to each group."""
    path = DATA_DIR / "hotlist_post_history.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_post_history(history: dict):
    path = DATA_DIR / "hotlist_post_history.json"
    path.write_text(json.dumps(history, indent=2))


def build_hotlist_email() -> tuple[str, str]:
    """Build the subject and body of the hotlist email."""
    today = datetime.now().strftime("%B %d, %Y")
    
    # Vary the subject slightly each day to avoid spam filters
    subjects = [
        f"HOTLIST – Senior Java/Spring Boot Developer Available C2C | {today}",
        f"Available Immediately – Java Backend Developer | C2C | {today}",
        f"C2C Consultant Available – Java 17, Spring Boot, Kafka, AWS | {today}",
        f"Updated Hotlist – Sr Java Developer | Green Card | Remote | {today}",
        f"Immediate Availability – Java/Microservices/Kafka | C2C | {today}",
    ]
    subject = subjects[date.today().timetuple().tm_yday % len(subjects)]
    
    body = f"""Hi,

Please find below my updated availability for C2C/Corp-to-Corp positions.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CONSULTANT HOTLIST — {today}

Name:           Bob Rikh
Role:           Senior Java Back-End Developer
Experience:     10+ Years
Work Auth:      Green Card Holder (No Sponsorship Required)
Availability:   Immediate
Rate:           $70-95/hr C2C
Location:       Parker, CO (100% Remote Preferred)
Contact:        bobrikh75@gmail.com | 347-268-5917
LinkedIn:       https://www.linkedin.com/in/bobrikh75/

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TECHNICAL SKILLS:

• Java 17, Core Java, Spring Boot, Spring Cloud, Spring MVC, Spring Security
• Microservices Architecture, REST APIs, GraphQL
• Apache Kafka, Event-Driven Architecture
• Kubernetes, Docker, AWS (EKS, S3, Lambda, SQS)
• MongoDB, Cassandra, PostgreSQL, Redis
• JUnit 5, Mockito, Integration Testing
• Maven, Git, Jenkins, CI/CD Pipelines
• Splunk, DataDog, Agile/Scrum

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LOOKING FOR:

• Contract positions (C2C / Corp-to-Corp)
• Java/Spring Boot backend development
• Microservices, Kafka, Cloud (AWS/GCP)
• 100% Remote preferred
• Long-term contracts (6+ months)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Please add me to your vendor list and share suitable daily requirements.
Available for immediate interviews and can start within 2 weeks.

Thank you,
Bob Rikh
bobrikh75@gmail.com
347-268-5917
"""
    return subject, body


def post_to_group(group: str, subject: str, body: str) -> bool:
    """Send the hotlist email to a Google Group via Gmail SMTP."""
    to_email = f"{group}@googlegroups.com"
    
    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        print(f"  ✅ Posted to {group}@googlegroups.com")
        return True
    except Exception as e:
        print(f"  ❌ Failed {group}: {str(e)[:80]}")
        return False


def main():
    print("=" * 60)
    print(f"HOTLIST POSTER — {datetime.now().strftime('%B %d, %Y')}")
    print("=" * 60)
    
    if not GMAIL_APP_PASSWORD:
        print("❌ GMAIL_APP_PASSWORD not set — cannot post")
        return
    
    # Get today's rotation of groups
    groups = get_todays_groups()
    print(f"  Today's groups ({len(groups)}): {', '.join(groups[:3])}...")
    
    # Load history — skip groups posted to in last 5 days
    history = load_post_history()
    today_str = date.today().isoformat()
    
    subject, body = build_hotlist_email()
    posted = 0
    failed = 0
    
    for group in groups:
        last_posted = history.get(group, "")
        if last_posted == today_str:
            print(f"  ⏭️ Already posted to {group} today")
            continue
        
        success = post_to_group(group, subject, body)
        if success:
            history[group] = today_str
            posted += 1
        else:
            failed += 1
        
        # Random delay between posts (look human)
        import time
        time.sleep(random.uniform(5, 15))
    
    save_post_history(history)
    
    print(f"\n{'=' * 60}")
    print(f"HOTLIST POSTING COMPLETE")
    print(f"  ✅ Posted: {posted}")
    print(f"  ❌ Failed: {failed}")
    print(f"  📧 Recruiters will see your availability and contact you")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
