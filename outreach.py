#!/usr/bin/env python3
"""
Bob Rikh — Recruiter Auto-Outreach
Finds recruiter emails from job postings → sends personalized CV email.
Max 10 emails/day. Never contacts same person twice.
"""
import json, os, re, smtplib, hashlib, ssl, urllib.request
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

CONTACTED_FILE = 'contacted.json'
CV_URL = 'https://drive.google.com/drive/folders/1sJRyHCTC2Xend6VWn6hM07VufWQdw_qV?usp=sharing'
APPOINTMENT_URL = 'https://calendar.google.com/calendar/u/0/appointments/AcZssZ22KPDPginBf34kMvb6wAFQUEHtG5sJ3PF_1k8='
MAX_EMAILS_PER_RUN = 10

EMAIL = os.environ.get('GMAIL_USER', 'bobrikh75@gmail.com')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD', '')

# ── Extract emails from job posting text ──
def extract_emails(text):
    """Pull real email addresses from job description."""
    if not text: return []
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', str(text))
    # Filter out junk
    skip = ['noreply', 'no-reply', 'donotreply', 'support@', 'info@indeed',
            'privacy@', 'abuse@', 'postmaster@', 'mailer-daemon', 'jobs@',
            'careers@indeed', 'apply@']
    return [e.lower() for e in emails if not any(s in e.lower() for s in skip)]

# ── Extract recruiter name from posting ──
def extract_recruiter_name(text):
    """Try to find recruiter name in posting."""
    if not text: return None
    patterns = [
        r'(?:contact|reach|email|send.*resume.*to)\s*:?\s*([A-Z][a-z]+ [A-Z][a-z]+)',
        r'(?:recruiter|hiring manager)\s*:?\s*([A-Z][a-z]+ [A-Z][a-z]+)',
        r'([A-Z][a-z]+ [A-Z][a-z]+)\s*(?:@|at\s)',
        r'(?:regards|thanks|sincerely),?\s*\n?\s*([A-Z][a-z]+ [A-Z][a-z]+)',
    ]
    for p in patterns:
        m = re.search(p, str(text))
        if m: return m.group(1).strip()
    return None

# ── Guess email patterns from name + company domain ──
def guess_email_patterns(first, last, domain):
    """Generate common corporate email patterns."""
    f, l = first.lower(), last.lower()
    return [
        f'{f}.{l}@{domain}',
        f'{f}{l}@{domain}',
        f'{f[0]}{l}@{domain}',
        f'{f}@{domain}',
        f'{f[0]}.{l}@{domain}',
        f'{l}.{f}@{domain}',
        f'{f}{l[0]}@{domain}',
    ]

# ── Verify email exists via SMTP (lightweight check) ──
def verify_email_smtp(email):
    """Quick SMTP check — does the mailbox exist?"""
    domain = email.split('@')[1]
    try:
        import dns.resolver
        mx = dns.resolver.resolve(domain, 'MX')
        mx_host = str(mx[0].exchange).rstrip('.')
        with smtplib.SMTP(mx_host, 25, timeout=10) as s:
            s.helo('gmail.com')
            s.mail('test@gmail.com')
            code, _ = s.rcpt(email)
            return code == 250
    except:
        return None  # Can't verify, assume valid

# ── Search Google for recruiter email ──
def search_recruiter_email(company):
    """Google search for recruiter email at company."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
    query = f'"{company}" recruiter email Java developer C2C'
    url = f'https://www.google.com/search?q={urllib.request.quote(query)}&num=5'
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            html = r.read().decode('utf-8', errors='ignore')
        return extract_emails(html)
    except:
        return []

# ── Load/save contacted tracker ──
def load_contacted():
    if os.path.exists(CONTACTED_FILE):
        with open(CONTACTED_FILE) as f: return json.load(f)
    return {}

def save_contacted(data):
    with open(CONTACTED_FILE, 'w') as f: json.dump(data, f, indent=2)

def email_hash(email): return hashlib.md5(email.lower().encode()).hexdigest()[:12]

# ── Build personalized email ──
def build_outreach_email(recruiter_name, job_title, company):
    name = recruiter_name or 'Hiring Manager'
    first = name.split()[0] if recruiter_name else 'Hi'

    subject = f'Java Backend Developer — C2C Available — Bob Rikh'

    body = f"""Hi {first},

I came across the {job_title} position at {company} and I'm very interested.

I'm a Java Backend Developer with hands-on experience in Spring Boot, Kafka, Kubernetes, Microservices, AWS, GraphQL, and MongoDB. Currently working as a contractor at Charter Communications.

Available for C2C / Corp-to-Corp. Green Card holder — no sponsorship needed.

📄 My CV: {CV_URL}
📅 Book a call: {APPOINTMENT_URL}
🔗 LinkedIn: https://www.linkedin.com/in/bobrikh75/

Best regards,
Bob Rikh
Parker, CO 80314
347-268-5917
bobrikh75@gmail.com"""

    return subject, body

# ── Send email via Gmail SMTP ──
def send_outreach(to_email, subject, body):
    if not GMAIL_APP_PASSWORD:
        print(f'  ⚠️  No GMAIL_APP_PASSWORD — skipping {to_email}')
        return False

    msg = MIMEMultipart()
    msg['From'] = f'Bob Rikh <{EMAIL}>'
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls()
            s.login(EMAIL, GMAIL_APP_PASSWORD)
            s.send_message(msg)
        return True
    except Exception as e:
        print(f'  ❌ Send failed to {to_email}: {e}')
        return False

# ── Main: process jobs and send outreach ──
def process_jobs(jobs_list):
    """
    jobs_list: list of dicts with keys: title, company, description, job_url, score
    Returns: list of outreach results
    """
    contacted = load_contacted()
    sent_count = 0
    results = []

    for job in jobs_list:
        if sent_count >= MAX_EMAILS_PER_RUN:
            print(f'  ⏸️  Daily limit reached ({MAX_EMAILS_PER_RUN})')
            break

        title = str(job.get('title', ''))
        company = str(job.get('company', ''))
        desc = str(job.get('description', ''))
        url = str(job.get('job_url', ''))

        # 1. Extract emails from posting
        emails = extract_emails(desc)

        # 2. Extract recruiter name
        recruiter_name = extract_recruiter_name(desc)

        # 3. If no email found, search Google
        if not emails and company and company != '?':
            emails = search_recruiter_email(company)

        if not emails:
            results.append({
                'job': title, 'company': company, 'status': 'no_email',
                'linkedin_search': f'https://www.linkedin.com/search/results/people/?keywords={urllib.request.quote(company + " recruiter")}&origin=GLOBAL_SEARCH_HEADER'
            })
            continue

        # 4. Send to first valid email (skip already contacted)
        for email in emails:
            eh = email_hash(email)
            if eh in contacted:
                print(f'  ⏭️  Already contacted: {email}')
                continue

            subject, body = build_outreach_email(recruiter_name, title, company)
            print(f'  📧 Sending to {email} for "{title}" @ {company}...')

            if send_outreach(email, subject, body):
                contacted[eh] = {
                    'email': email, 'date': datetime.now().isoformat(),
                    'job': title, 'company': company, 'url': url,
                    'recruiter': recruiter_name,
                }
                sent_count += 1
                results.append({
                    'job': title, 'company': company, 'email': email,
                    'recruiter': recruiter_name, 'status': 'sent'
                })
                print(f'  ✅ Sent! ({sent_count}/{MAX_EMAILS_PER_RUN})')
            break  # One email per job

    save_contacted(contacted)
    print(f'\n📊 Outreach: {sent_count} sent / {len(contacted)} total contacted / {len(jobs_list)} jobs processed')
    return results
