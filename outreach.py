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

# ── Bob's actual Gmail signature (extracted from Gmail settings) ──
PHOTO_URL = 'https://lh7-rt.googleusercontent.com/docsz/AD_4nXdTFpRiWmBy6NPYZ4s2J9tMu1RN8HSnyakDELLUiBK4MhkV-W-wO9EQJvCK5DNrSuV4hVHjOQ85QuNff994QwraSCUHcIXnGAYaRyWa8eF43nJqFlEV4-VSYyAcOgkAYT1cWiDbZ0zuvhpmyr8XsfBmUaDI?key=f7Af-7daiBWgEMeWs4Hs_Q'
BOOK_URL = 'https://calendar.app.google/DG7ug2xFUuQneV2r6'

SIGNATURE_HTML = f'''<table style="border:none;border-collapse:collapse"><colgroup><col width="262"><col width="331"></colgroup><tbody><tr style="height:207pt"><td style="border-left:solid #ffffff 0.75pt;border-right:solid #1155cc 3pt;border-bottom:solid #ffffff 0.75pt;border-top:solid #ffffff 0.75pt;vertical-align:top;padding:5pt"><p dir="ltr" style="line-height:1.44;margin:0"><span style="border:none;display:inline-block;overflow:hidden;width:248px;height:248px"><img src="{PHOTO_URL}" width="248" height="248" style="margin:0"></span></p></td><td style="border-left:solid #1155cc 3pt;border-right:solid #ffffff 0.75pt;border-bottom:solid #ffffff 0.75pt;border-top:solid #ffffff 0.75pt;vertical-align:top;padding:5pt"><p dir="ltr" style="line-height:1.44;text-align:center;margin:0"><span style="font-size:18pt;font-family:\'Times New Roman\',serif;color:#1155cc;font-weight:700">Bob Rikh</span></p><p dir="ltr" style="line-height:1.44;text-align:center;margin:0"><span style="font-size:13pt;font-family:\'Times New Roman\',serif">Parker, CO, 80314&nbsp; </span><a href="mailto:bobrikh75@gmail.com"><span style="font-size:13pt;font-family:\'Times New Roman\',serif;color:#1155cc;font-weight:700">Gmail</span></a><span style="font-size:13pt;font-family:\'Times New Roman\',serif;font-weight:700">&nbsp; 347-268-5917 </span><a href="{BOOK_URL}"><span style="font-size:13pt;font-family:\'Times New Roman\',serif;color:#1155cc;font-weight:700">Book an appointment</span></a><span style="font-size:13pt;font-family:\'Times New Roman\',serif;font-weight:700">&nbsp;&nbsp;</span><a href="{CV_URL}"><b style="font-size:13pt;font-family:\'Times New Roman\',serif;color:#1155cc">CV</b></a><span style="font-size:13pt;font-family:\'Times New Roman\',serif;font-weight:700">&nbsp;&nbsp;</span><a href="https://www.linkedin.com/in/bobrikh75/"><b style="font-size:13pt;font-family:\'Times New Roman\',serif;color:#1155cc">LinkedIn</b></a></p><br><h1 dir="ltr" style="line-height:1.44;text-align:center;margin:0"><span style="font-size:12pt;font-family:\'Times New Roman\',serif;color:#000;font-weight:normal">Experienced Java Back-End Developer &amp; Specializing in Spring Ecosystem with QA Automation Test Agile Methodologies&#x2551;RESTful APIs&#x2551;QA&#x2551;Microservices&#x2551;AWS Cloud &#x2551;Apache Kafka &#x2551;Docker &#x2551; Kubernetes</span></h1></td></tr></tbody></table>'''

def build_outreach_email(recruiter_name, job_title, company):
    name = recruiter_name or ''
    first = name.split()[0] if name else ''
    greeting = f'Hi {first},' if first else 'Hello,'

    subject = f'{job_title} — C2C Available — Bob Rikh'

    html = f"""<div style="font-family:Arial,sans-serif;font-size:14px;color:#333">
<p>{greeting}</p>

<p>I hope this message finds you well. I came across the <strong>{job_title}</strong> position at <strong>{company}</strong> and wanted to reach out directly as I believe my background is a strong match for this role.</p>

<p>I'm an experienced Java Backend Developer currently working as a contractor at Charter Communications, with hands-on expertise in:</p>

<ul style="margin:5px 0;padding-left:20px">
<li><strong>Java 17, Spring Boot, Spring Cloud, Spring Security</strong></li>
<li><strong>Apache Kafka, Kubernetes, Docker, AWS</strong></li>
<li><strong>Microservices, GraphQL, REST APIs</strong></li>
<li><strong>MongoDB, Cassandra, PostgreSQL, Redis</strong></li>
<li><strong>CI/CD, Jenkins, DataDog, Splunk</strong></li>
</ul>

<p>I'm available for <strong>C2C / Corp-to-Corp</strong> engagement and can start immediately.<br>
<strong>Green Card holder — no sponsorship required.</strong></p>

<p>I'd welcome the opportunity to discuss how I can contribute to your team. Please feel free to review my CV or schedule a call at your convenience.</p>

<br>
{SIGNATURE_HTML}
</div>"""

    return subject, html

# ── Send email via Gmail SMTP ──
def send_outreach(to_email, subject, html):
    if not GMAIL_APP_PASSWORD:
        print(f'  ⚠️  No GMAIL_APP_PASSWORD — skipping {to_email}')
        return False

    msg = MIMEMultipart('alternative')
    msg['From'] = f'Bob Rikh <{EMAIL}>'
    msg['To'] = to_email
    msg['Subject'] = subject
    msg['Reply-To'] = EMAIL
    msg['X-Mailer'] = 'Gmail'
    # Plain text version (required — emails without it get flagged as spam)
    plain = f"""Hello,

I came across a position at your company and wanted to reach out.

I'm an experienced Java Backend Developer (Spring Boot, Kafka, Kubernetes, AWS, Microservices) currently contracting at Charter Communications.

Available for C2C / Corp-to-Corp. Green Card holder — no sponsorship needed.

CV: {CV_URL}
Book a call: {BOOK_URL}
LinkedIn: https://www.linkedin.com/in/bobrikh75/

Best regards,
Bob Rikh
Parker, CO 80314
347-268-5917
bobrikh75@gmail.com"""
    msg.attach(MIMEText(plain, 'plain'))
    msg.attach(MIMEText(html, 'html'))

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

            subject, html = build_outreach_email(recruiter_name, title, company)
            print(f'  📧 Sending to {email} for "{title}" @ {company}...')

            if send_outreach(email, subject, html):
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
