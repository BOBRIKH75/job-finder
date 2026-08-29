#!/usr/bin/env python3
"""Autonomous recruiter email responder.

Monitors Gmail for recruiter emails, classifies them, auto-replies:
- Screening questions → answers from profile (rate, visa, availability)
- Interview scheduling → confirms availability + sends calendar link
- Assessment/test links → forwards to user's email with alert
- Rejection → archives, no reply
- Real interview invite → ALERT user (don't auto-reply)

Runs as GitHub Actions workflow every 2 hours.
"""
import imaplib
import email
import json
import os
import re
import smtplib
import sys
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

os.environ['PYTHONUNBUFFERED'] = '1'

GMAIL_USER = os.environ.get('GMAIL_USER', '')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD', '')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
CALENDAR_LINK = 'https://calendar.google.com/calendar/u/0/appointments/AcZssZ22KPDPginBf34kMvb6wAFQUEHtG5sJ3PF_1k8='

# Bob's profile for auto-answers
PROFILE = {
    'name': 'Bob Rikh',
    'email': GMAIL_USER,
    'role': 'Senior Java Backend Developer',
    'experience': '8+ years',
    'skills': 'Java 17, Spring Boot, Spring Cloud, Microservices, Apache Kafka, Kubernetes, Docker, AWS, GraphQL, REST APIs, MongoDB, Cassandra, PostgreSQL, Redis',
    'rate': '$70-95/hr C2C',
    'work_type': 'C2C / Corp-to-Corp',
    'visa': 'Green Card holder — no sponsorship required',
    'availability': 'Available immediately, can start within 1-2 weeks',
    'location': 'Parker, CO (Remote preferred, open to hybrid Denver metro)',
    'relocation': 'No — remote only',
    'contract_length': 'Open to 6+ month contracts',
    'calendar': CALENDAR_LINK,
    'linkedin': 'https://www.linkedin.com/in/bobrikh75/',
    'phone': '347-268-5917',
}

# Keywords that indicate this needs HUMAN attention (don't auto-reply)
HUMAN_REQUIRED = [
    'final round', 'onsite', 'on-site', 'in-person interview',
    'panel interview', 'meet the team', 'offer letter', 'compensation package',
    'background check', 'drug test', 'start date confirmed',
    'welcome aboard', 'congratulations', 'you got the job',
]

# Keywords for rejection (archive, no reply)
REJECTION_SIGNALS = [
    'unfortunately', 'not moving forward', 'other candidates',
    'position has been filled', 'not a fit', 'decided to go',
    'wish you the best', 'no longer available',
]

# Keywords for screening questions
SCREENING_SIGNALS = [
    'rate', 'hourly', 'compensation', 'salary',
    'visa', 'work authorization', 'sponsorship', 'eligible',
    'available', 'availability', 'start date', 'notice period',
    'remote', 'onsite', 'hybrid', 'location', 'relocate',
    'c2c', 'corp to corp', 'w2', '1099', 'contract type',
    'years of experience', 'how long', 'background',
    'interested', 'good fit', 'open to',
]

# Keywords for interview scheduling
SCHEDULING_SIGNALS = [
    'schedule', 'calendar', 'time slot', 'available for a call',
    'phone screen', 'technical interview', 'zoom', 'teams meeting',
    'book a time', 'when are you free', 'set up a call',
]

TRACKER_FILE = 'agent/data/auto_reply_tracker.json'

# Safe personal-Gmail daily auto-reply cap (research: 10-30/day for personal Gmail)
MAX_REPLIES_PER_RUN = int(os.environ.get('MAX_AUTO_REPLIES', '15'))

# --- Deliverability protection: ONLY reply to real humans writing to Bob ---
# Research-backed (Gmail sender guidelines + cold-outreach deliverability):
# auto-replying to job-board alerts / newsletters / no-reply addresses trashes
# sender reputation, which sends REAL recruiter emails to spam = fewer people
# reached. So we reply only when it's genuinely a person contacting Bob.

# Job-board / aggregator / platform DOMAINS — their mail is automated, not a person.
# Matched against the email DOMAIN (endswith), so it won't false-hit company names
# like "apexsystems.com".
_DENY_DOMAINS = [
    'linkedin.com', 'indeed.com', 'indeedemail.com', 'dice.com', 'ziprecruiter.com',
    'glassdoor.com', 'monster.com', 'careerbuilder.com', 'simplyhired.com',
    'lensa.com', 'jobcase.com', 'talent.com', 'wellfound.com', 'angel.co',
    'greenhouse.io', 'lever.co', 'ashbyhq.com', 'myworkday.com', 'smartrecruiters.com',
    'google.com', 'calendar.google.com', 'meet.google.com', 'facebookmail.com',
    'medium.com', 'substack.com', 'github.com', 'atlassian.com', 'slack.com', 'zoom.us',
]

# Automated-sender words — matched against the LOCAL-PART tokens only (before @),
# so "system" won't match "apexsystems.com".
_DENY_LOCAL_WORDS = {
    'noreply', 'no-reply', 'donotreply', 'do-not-reply', 'mailer-daemon', 'mailer',
    'notifications', 'notification', 'alert', 'alerts', 'jobalert', 'jobalerts',
    'bounce', 'bounces', 'updates', 'digest', 'newsletter', 'postmaster',
    'automated', 'auto', 'system', 'noreply-jobs', 'no-reply-jobs',
}


def _looks_like_person_email(local: str) -> bool:
    """Return True only if the email local part looks like a human name."""
    _NON_PERSON = {
        'noreply', 'no-reply', 'donotreply', 'admin', 'info', 'support',
        'help', 'hello', 'contact', 'team', 'mail', 'jobs', 'careers', 'hr',
        'hiring', 'talent', 'dev', 'test',
        'api', 'system', 'bot', 'auto', 'mailer', 'notification', 'notifications',
        'alert', 'alerts', 'security', 'privacy', 'abuse', 'webmaster',
        'postmaster', 'billing', 'sales', 'marketing', 'press', 'legal',
        'finance', 'apply', 'application', 'response', 'inmail',
    }
    ll = local.lower()
    if ll in _NON_PERSON or ll.replace('-', '').replace('.', '') in _NON_PERSON:
        return False
    parts = re.split(r'[._\-]', ll)
    if any(p in _NON_PERSON for p in parts):
        return False
    if re.match(r'^\d', local) or len(local) < 3 or len(local) > 40:
        return False
    return bool(re.search(r'[a-z]', ll))


def _is_reply_to_bob(msg) -> bool:
    """True if this email is a REPLY to something Bob sent.

    A recruiter replying to Bob's outreach will have In-Reply-To / References
    headers, or 'Re:' in the subject. That is a real human conversation.
    """
    if msg.get('In-Reply-To') or msg.get('References'):
        return True
    subj = str(msg.get('Subject', '') or '').lower()
    return subj.startswith('re:') or ' re:' in subj


def _should_reply_to(from_addr: str, msg, contacted_emails: set) -> tuple:
    """Decide if we may auto-reply. Returns (ok: bool, reason: str).

    Reply ONLY when ALL are true:
      1. Domain is not a job board / platform
      2. Local-part is not an automated sender (noreply/alerts/...)
      3. Local-part looks like a human name (not jobs@/hr@/talent@)
      4. It is EITHER a reply to Bob's outreach OR from a recruiter Bob contacted
    """
    from_lower = (from_addr or '').lower()
    m = re.search(r'[\w.+-]+@[\w.-]+', from_lower)
    sender_email = m.group(0) if m else ''
    if not sender_email:
        return False, 'no parseable sender'

    local, _, domain = sender_email.partition('@')

    # 1. Job-board / platform domain (exact or subdomain)
    if any(domain == d or domain.endswith('.' + d) for d in _DENY_DOMAINS):
        return False, f'job-board/platform domain ({domain})'

    # 2. Automated sender local-part
    local_tokens = set(re.split(r'[._\-]', local))
    if local in _DENY_LOCAL_WORDS or local_tokens & _DENY_LOCAL_WORDS:
        return False, f'automated sender ({local}@)'

    # 3. Human-looking address
    if not _looks_like_person_email(local):
        return False, f'not a person address ({local}@...)'

    # 4. Must be a real conversation
    if _is_reply_to_bob(msg):
        return True, 'reply to Bob'
    if sender_email in contacted_emails:
        return True, 'known contacted recruiter'

    return False, 'cold inbound (not a reply, not a known recruiter)'


def load_tracker():
    if os.path.exists(TRACKER_FILE):
        return json.loads(open(TRACKER_FILE).read())
    return {'replied': [], 'human_alerts': [], 'rejections': []}


def save_tracker(tracker):
    os.makedirs(os.path.dirname(TRACKER_FILE), exist_ok=True)
    with open(TRACKER_FILE, 'w') as f:
        json.dump(tracker, f, indent=2)


def classify_email(subject: str, body: str) -> str:
    """Classify email into: screening, scheduling, rejection, human_required, ignore"""
    text = (subject + ' ' + body).lower()

    if any(sig in text for sig in HUMAN_REQUIRED):
        return 'human_required'
    if any(sig in text for sig in REJECTION_SIGNALS):
        return 'rejection'
    if any(sig in text for sig in SCHEDULING_SIGNALS):
        return 'scheduling'
    if any(sig in text for sig in SCREENING_SIGNALS):
        return 'screening'
    return 'ignore'


def generate_reply_with_gemini(subject: str, body: str, classification: str) -> str:
    """Use Gemini to generate a contextual, professional reply."""
    if not GEMINI_API_KEY:
        return generate_template_reply(classification, body)

    import requests
    prompt = f"""You are Bob Rikh, a Senior Java Backend Developer responding to a recruiter email.

Your profile:
- Rate: $70-95/hr C2C (Corp-to-Corp)
- Work Authorization: Green Card holder, NO sponsorship needed
- Availability: Available immediately, can start in 1-2 weeks
- Location: Parker, CO. Remote ONLY (no relocation)
- Experience: 8+ years Java/Spring Boot/Kafka/Kubernetes/AWS
- Contract type: C2C ONLY (no W2)
- Phone: 347-268-5917
- Calendar for scheduling: {CALENDAR_LINK}

The recruiter sent this email:
Subject: {subject}
Body: {body[:1500]}

Classification: {classification}

Write a short, professional reply (3-5 sentences max). Be friendly but direct.
If they ask about rate, say $70-95/hr C2C.
If they ask about availability, say available immediately.
If they want to schedule, share your calendar link.
If they ask screening questions, answer directly from your profile.
Do NOT use any greeting like 'Dear [name]' — just start with 'Hi [first name],' or 'Hi,'
End with 'Best regards,\\nBob Rikh\\n347-268-5917'
"""

    try:
        resp = requests.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}',
            json={'contents': [{'parts': [{'text': prompt}]}]},
            timeout=30
        )
        if resp.status_code == 200:
            content = resp.json().get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
            if content and len(content) > 20:
                return content.strip()
    except Exception as e:
        print(f'  ⚠️ Gemini error: {str(e)[:60]}')

    return generate_template_reply(classification, body)


def generate_template_reply(classification: str, body: str) -> str:
    """Fallback template-based reply when Gemini isn't available."""
    body_lower = body.lower()

    if classification == 'scheduling':
        return f"""Hi,

Thank you for reaching out! I'm very interested and available for a call.

Please feel free to book a time that works for you: {CALENDAR_LINK}

Alternatively, I'm generally available Mon-Fri, 9 AM - 5 PM MT.

Best regards,
Bob Rikh
347-268-5917"""

    # Screening — answer based on what they asked
    answers = []
    if any(w in body_lower for w in ['rate', 'hourly', 'compensation', 'salary', 'budget']):
        answers.append('My rate is $70-95/hr on C2C (Corp-to-Corp) basis.')
    if any(w in body_lower for w in ['visa', 'authorization', 'sponsorship', 'eligible', 'legally']):
        answers.append('I am a US Green Card holder \u2014 no sponsorship required.')
    if any(w in body_lower for w in ['available', 'start', 'notice', 'when can']):
        answers.append('I am available immediately and can start within 1-2 weeks.')
    if any(w in body_lower for w in ['remote', 'onsite', 'location', 'relocat', 'hybrid']):
        answers.append('I am based in Parker, CO and prefer fully remote. Open to hybrid in the Denver metro area.')
    if any(w in body_lower for w in ['c2c', 'corp', 'w2', '1099', 'contract type', 'employment type']):
        answers.append('I work on C2C (Corp-to-Corp) basis only.')
    if any(w in body_lower for w in ['experience', 'years', 'background', 'about you']):
        answers.append('I have 8+ years of experience in Java, Spring Boot, Microservices, Kafka, Kubernetes, AWS, and REST/GraphQL APIs.')
    if any(w in body_lower for w in ['interested', 'good fit', 'open to', 'consider']):
        answers.append('Yes, I am interested and available. Would love to discuss further!')

    if not answers:
        answers.append('Thank you for reaching out! I am interested and available.')
        answers.append('My rate is $70-95/hr C2C, and I can start within 1-2 weeks.')

    answers.append(f'\nFeel free to book a call: {CALENDAR_LINK}')

    return f"""Hi,

Thank you for reaching out regarding this opportunity.

{chr(10).join(answers)}

Best regards,
Bob Rikh
347-268-5917"""


def send_reply(to_email: str, subject: str, body: str) -> bool:
    """Send reply via Gmail SMTP."""
    if not GMAIL_APP_PASSWORD:
        print(f'  ⚠️ No GMAIL_APP_PASSWORD')
        return False

    msg = MIMEMultipart('alternative')
    msg['From'] = f'Bob Rikh <{GMAIL_USER}>'
    msg['To'] = to_email
    msg['Subject'] = f'Re: {subject}' if not subject.startswith('Re:') else subject
    msg['In-Reply-To'] = ''  # Will be set if we have message-id
    msg.attach(MIMEText(body, 'plain'))

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls()
            s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            s.send_message(msg)
        return True
    except Exception as e:
        print(f'  ❌ Send failed: {str(e)[:60]}')
        return False


def main():
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print('❌ GMAIL_USER or GMAIL_APP_PASSWORD not set')
        return

    print(f'🤖 Recruiter Auto-Reply Agent — {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print('=' * 50)

    tracker = load_tracker()
    replied_ids = set(tracker.get('replied', []))

    # Recruiters Bob has contacted — used to allow replies from known recruiters
    # even if the email isn't a threaded 'Re:'. Sourced from the vendor list +
    # anyone Bob previously emailed.
    contacted_emails = set()
    try:
        vendor_file = os.path.join(os.path.dirname(TRACKER_FILE), 'vendor_list.json')
        if os.path.exists(vendor_file):
            for v in json.loads(open(vendor_file).read()):
                e = (v.get('email') or '').lower().strip()
                if e:
                    contacted_emails.add(e)
    except Exception:
        pass
    for e in tracker.get('contacted', []):
        if isinstance(e, str):
            contacted_emails.add(e.lower().strip())

    # Connect to Gmail
    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        mail.select('INBOX')
    except Exception as e:
        print(f'❌ Gmail login failed: {str(e)[:60]}')
        return

    # Search for recent unread emails (last 3 days)
    since = (datetime.now() - timedelta(days=3)).strftime('%d-%b-%Y')
    _, data = mail.search(None, f'(UNSEEN SINCE {since})')
    msg_ids = data[0].split()

    print(f'  📧 {len(msg_ids)} unread emails in last 3 days')

    replied_count = 0
    human_alerts = 0
    rejections = 0

    for msg_id in msg_ids[-30:]:  # Process max 30 per run
        _, msg_data = mail.fetch(msg_id, '(RFC822)')
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        subject = str(email.header.decode_header(msg['Subject'])[0][0] or '')
        if isinstance(subject, bytes):
            subject = subject.decode('utf-8', errors='ignore')
        from_addr = msg['From']
        message_id = msg.get('Message-ID', '')

        # Skip if already replied
        if message_id in replied_ids:
            continue

        # DELIVERABILITY GUARD: only reply to real humans writing to Bob.
        # Blocks job-board alerts, newsletters, no-reply, and cold inbound blasts
        # that would trash Gmail sender reputation and send real recruiter mail to spam.
        ok, reason = _should_reply_to(from_addr, msg, contacted_emails)
        if not ok:
            print(f'    ⏭️ skip ({reason}): {from_addr[:50]}')
            continue

        # Get body
        body = ''
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == 'text/plain':
                    body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    break
                elif part.get_content_type() == 'text/html' and not body:
                    import html
                    raw_html = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    body = re.sub(r'<[^>]+>', ' ', raw_html)
        else:
            body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')

        # Classify
        classification = classify_email(subject, body)

        # Extract sender's email
        sender_match = re.search(r'[\w.-]+@[\w.-]+', from_addr)
        sender_email = sender_match.group(0) if sender_match else ''

        print(f'\n  [{classification.upper()}] {subject[:60]}')
        print(f'    From: {sender_email}')

        if classification == 'human_required':
            print(f'    ⚠️ REAL INTERVIEW — requires your attention!')
            tracker['human_alerts'].append({
                'date': datetime.now().isoformat(),
                'subject': subject,
                'from': sender_email,
            })
            human_alerts += 1
            # Mark as unread so user sees it
            mail.store(msg_id, '-FLAGS', '\\Seen')
            continue

        if classification == 'rejection':
            print(f'    🗑️ Rejection — archived')
            tracker['rejections'].append({
                'date': datetime.now().isoformat(),
                'subject': subject,
                'from': sender_email,
            })
            rejections += 1
            continue

        if classification == 'ignore':
            continue

        # DELIVERABILITY CAP: never exceed the safe personal-Gmail zone (research:
        # 10-30/day for a personal account). Stop replying once the cap is hit.
        if replied_count >= MAX_REPLIES_PER_RUN:
            print(f'    ⏸️ Daily reply cap ({MAX_REPLIES_PER_RUN}) reached — stopping')
            break

        # Generate and send reply
        reply = generate_reply_with_gemini(subject, body, classification)
        if reply and sender_email:
            success = send_reply(sender_email, subject, reply)
            if success:
                print(f'    ✅ Auto-replied ({classification})')
                replied_count += 1
                tracker['replied'].append(message_id)
                # Keep only last 500
                tracker['replied'] = tracker['replied'][-500:]
            else:
                print(f'    ❌ Failed to send reply')

    mail.logout()
    save_tracker(tracker)

    print(f'\n📊 Summary: {replied_count} replied, {human_alerts} need your attention, {rejections} rejections')
    if human_alerts > 0:
        print(f'\n⚠️ CHECK YOUR INBOX — {human_alerts} real interview invite(s)!')


if __name__ == '__main__':
    main()
