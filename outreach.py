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

# ── US-relevance filter (target REAL US recruiters, skip offshore C2C body-shops) ──
# Business-signal filter ONLY (not national origin — that's inaccurate + wrong to code).
# It scores a job/recruiter on signals that distinguish a real US recruiter / direct US
# employer from an offshore bench-sales C2C spam shop. Set US_FILTER_OFF=1 to disable.

# Verified large US staffing / direct-employer firms — always ALLOW (SIA 2026 top-firms).
_US_ALLOW_FRAGMENTS = {
    "teksystems", "allegis", "aerotek", "insightglobal", "insight global",
    "apexsystems", "apex systems", "kforce", "roberthalf", "robert half",
    "randstad", "experis", "manpower", "beaconhill", "beacon hill",
    "motionrecruitment", "motion recruitment", "brooksource", "kavaliro",
    "bayforce", "judge", "signaturecg", "collabera",  # Collabera is US-HQ'd (NJ)
    "dexian", "inspyr", "mondo", "jobot", "cybercoders", "matlensilver",
    "eliassen", "harnham", "aquent", "astoncarter", "calculatedhire",
}

# Email local-parts that scream "bench sales / hotlist C2C spam" (not a real 1:1 recruiter).
_BENCH_LOCAL_PARTS = ("benchsales", "bench", "hotlist", "marketing", "resumes",
                      "submissions", "requirements", "req", "c2c", "consultants")

# Phrases that indicate a multi-vendor bench/C2C body-shop rather than a direct US role.
_BODYSHOP_PHRASES = ("corp to corp only", "c2c only", "corp-to-corp only", "bench",
                     "implementation partner", "prime vendor", "multiple positions",
                     "h1b transfer", "opt/cpt", "opt cpt", "gc-ept", "whatsapp",
                     "share your hotlist", "send hotlist")


def _domain_of(email):
    return (email.split('@')[1].lower() if '@' in email else '')


def us_relevance_score(email, company, description):
    """Return (score, reasons). Higher = more likely a REAL US recruiter/employer.
    score >= US_MIN_SCORE (default 0) passes. Negative = likely offshore C2C spam."""
    score, reasons = 0, []
    e, comp, desc = (email or '').lower(), (company or '').lower(), (description or '').lower()
    dom = _domain_of(e)
    local = e.split('@')[0] if '@' in e else ''

    # STRONG ALLOW: known US firm by name or domain
    if any(f in comp or f.replace(' ', '') in dom for f in _US_ALLOW_FRAGMENTS):
        score += 5; reasons.append('known-US-firm')

    # Free webmail recruiter = usually an individual bench-sales rep, not a firm recruiter
    if dom in ('gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'aol.com'):
        score -= 2; reasons.append('free-webmail')
    elif dom:
        score += 1; reasons.append('corp-domain')

    # Bench-sales email local part
    if any(local.startswith(b) or local == b for b in _BENCH_LOCAL_PARTS):
        score -= 3; reasons.append(f'bench-local:{local[:12]}')

    # +91 India phone in the posting (a real US role lists a +1 number)
    if re.search(r'\+?91[\s\-]?\d{10}\b|\b0091\b', desc):
        score -= 3; reasons.append('india-phone')
    if re.search(r'\bwhatsapp\b', desc):
        score -= 2; reasons.append('whatsapp')

    # Body-shop / bench language
    hits = [p for p in _BODYSHOP_PHRASES if p in desc]
    if hits:
        score -= 2 * len(hits); reasons.append('bodyshop:' + ','.join(hits[:2]))

    # Explicit US-direct signals
    if any(s in desc for s in ('w2 only', 'us citizen', 'gc holder only',
                               'no c2c', 'direct hire', 'full-time employee')):
        score += 2; reasons.append('us-direct-signal')

    return score, reasons


def passes_us_filter(email, company, description):
    """True if this recruiter/job clears the US-relevance bar. Requires 2+ negative
    signals before blocking (per research — avoid false blocks on real US firms)."""
    if os.environ.get('US_FILTER_OFF') == '1':
        return True, 0, ['filter-off']
    min_score = int(os.environ.get('US_MIN_SCORE', '0'))
    score, reasons = us_relevance_score(email, company, description)
    neg = sum(1 for r in reasons if r.split(':')[0] in
              ('free-webmail', 'bench-local', 'india-phone', 'whatsapp', 'bodyshop'))
    # Block only when clearly offshore-C2C: below threshold AND 2+ independent neg signals,
    # and NOT a known US firm.
    if score < min_score and neg >= 2 and 'known-US-firm' not in reasons:
        return False, score, reasons
    return True, score, reasons


def hunter_verify_email(email):
    """Verify deliverability via Hunter.io (2026 API). Returns:
      True  = safe to send (status valid, not catch-all)
      False = do NOT send (invalid/disposable/blocked)
      None  = unknown / no API key / accept-all (let SMTP decide, don't hard-block)
    Endpoint: GET https://api.hunter.io/v2/email-verifier (field 'status')."""
    key = os.environ.get('HUNTER_API_KEY', '')
    if not key or not email:
        return None
    try:
        q = urllib.request.quote(email)
        url = f"https://api.hunter.io/v2/email-verifier?email={q}&api_key={key}"
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=12, context=ctx) as r:
            data = json.loads(r.read().decode('utf-8', errors='ignore')).get('data', {})
        status = (data.get('status') or '').lower()
        if status in ('invalid', 'disposable') or data.get('block'):
            return False
        if status == 'valid' and not data.get('accept_all'):
            return True
        return None   # accept_all / webmail / unknown → don't hard-block
    except Exception:
        return None


CONTACTED_FILE = 'contacted.json'
CV_URL = 'https://drive.google.com/drive/folders/1sJRyHCTC2Xend6VWn6hM07VufWQdw_qV?usp=sharing'
APPOINTMENT_URL = 'https://calendar.google.com/calendar/u/0/appointments/AcZssZ22KPDPginBf34kMvb6wAFQUEHtG5sJ3PF_1k8='
MAX_EMAILS_PER_RUN = 50

EMAIL = os.environ.get('GMAIL_USER', 'bobrikh75@gmail.com')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD', '')

# Words that indicate a service/technical email — not a human recruiter
_NON_PERSON_WORDS = {
    "allow", "origin", "noreply", "no-reply", "donotreply", "admin",
    "info", "support", "help", "hello", "contact", "team", "mail",
    "jobs", "careers", "hr", "hiring", "talent", "recruit",
    "dev", "test", "api", "system", "bot", "auto", "mailer",
    "notification", "alert", "security", "privacy", "abuse",
    "webmaster", "postmaster", "hostmaster", "billing", "sales",
    "marketing", "press", "pr", "legal", "finance", "apply",
}


def _looks_like_person_email(local: str) -> bool:
    """Return True only if the email local part looks like a human name."""
    local_lower = local.lower()
    # Check the full string first (catches "no-reply", "do-not-reply", etc.)
    if local_lower in _NON_PERSON_WORDS or local_lower.replace('-', '') in _NON_PERSON_WORDS:
        return False
    parts = re.split(r'[._\-]', local_lower)
    # Reject if any segment matches a known non-person word
    if any(p in _NON_PERSON_WORDS for p in parts):
        return False
    # Reject if starts with a digit or is too short/long
    if re.match(r'^\d', local) or len(local) < 3 or len(local) > 40:
        return False
    # Must contain at least one letter
    return bool(re.search(r'[a-z]', local.lower()))


# ── Extract emails from job posting text ──
def extract_emails(text):
    """Pull real email addresses from job description — human names only."""
    if not text: return []
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', str(text))
    # Filter obvious junk domains first
    skip_domains = ['indeed.com', 'linkedin.com', 'dice.com', 'greenhouse.io', 'lever.co']
    filtered = [e.lower() for e in emails if not any(d in e.lower() for d in skip_domains)]
    # Then keep only emails whose local part looks like a real person's name
    return [e for e in filtered if _looks_like_person_email(e.split('@')[0])]

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


def _company_to_domain(company: str) -> str:
    """Best-effort company name -> email domain (for Hunter.io lookup).

    'Beacon Hill' -> 'beaconhill.com', 'Apex Systems' -> 'apexsystems.com'.
    Not perfect, but Hunter validates the domain and returns nothing if wrong,
    so a bad guess simply yields no result (safe).
    """
    if not company:
        return ""
    name = company.lower()
    # Drop common corporate suffixes that are not part of the domain
    for suffix in (" inc.", " inc", " llc", " ltd", " corp", " corporation",
                   " group", " technologies", " technology", " solutions",
                   " consulting", " systems", " services", " co.", " company",
                   ", a day & zimmermann company"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    # Keep only alphanumerics
    slug = re.sub(r'[^a-z0-9]', '', name)
    return f"{slug}.com" if slug else ""


def _hunter_domain_search(domain: str) -> list:
    """Query Hunter.io for HR/recruiter emails at a domain. Returns [emails]."""
    key = os.environ.get("HUNTER_API_KEY", "")
    if not key or not domain:
        return []
    try:
        q = urllib.request.quote(domain)
        url = (f"https://api.hunter.io/v2/domain-search?domain={q}"
               f"&type=personal&department=human_resources&limit=5&api_key={key}")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=12, context=ctx) as r:
            data = json.loads(r.read().decode('utf-8', errors='ignore'))
        emails = [e.get("value", "").lower()
                  for e in data.get("data", {}).get("emails", [])
                  if e.get("value")]
        return [e for e in emails if e]
    except Exception:
        return []


def find_company_recruiters(company: str, description: str = "") -> list:
    """Find recruiter email(s) for a job — REAL path that produces callbacks.

    Priority order (best-first):
      1. Emails embedded in the job DESCRIPTION — staffing/C2C posts almost
         always include the recruiter's direct email. Free, most reliable.
      2. Hunter.io domain search (HR department) using a guessed domain.
      3. Google scrape (legacy, usually blocked) — last resort.

    Returns a de-duplicated list of human-looking recruiter emails.
    """
    found = []

    # 1) Description first — highest value for C2C/staffing posts
    if description:
        found.extend(extract_emails(description))

    # 2) Hunter.io on the guessed company domain
    if not found:
        domain = _company_to_domain(company)
        found.extend(_hunter_domain_search(domain))

    # 3) Legacy Google scrape (rarely works, but harmless)
    if not found:
        try:
            found.extend(search_recruiter_email(company))
        except Exception:
            pass

    # De-dup, preserve order
    seen, out = set(), []
    for e in found:
        e = e.lower().strip()
        if e and e not in seen:
            seen.add(e)
            out.append(e)
    return out

# ── Load/save contacted tracker ──
def load_contacted():
    if os.path.exists(CONTACTED_FILE):
        try:
            with open(CONTACTED_FILE) as f: return json.load(f)
        except (json.JSONDecodeError, ValueError) as e:
            print(f'⚠️  Corrupt JSON in {CONTACTED_FILE} ({e}) — resetting to empty; will be rewritten on save')
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

RESEND_KEY = os.environ.get('RESEND_KEY', '')

PLAIN_TEMPLATE = f"""Hello,

I came across a position at your company and wanted to reach out.

I'm an experienced Java Backend Developer (Spring Boot, Kafka, Kubernetes, AWS, Microservices)
currently contracting at Charter Communications.

Available for C2C / Corp-to-Corp. Green Card holder — no sponsorship needed.

CV: {CV_URL}
Book a call: {BOOK_URL}
LinkedIn: https://www.linkedin.com/in/bobrikh75/

Best regards,
Bob Rikh
Parker, CO 80314
347-268-5917
bobrikh75@gmail.com"""


def _send_via_resend(to_email, subject, html) -> bool:
    """Send via Resend API — better deliverability than raw Gmail SMTP."""
    import urllib.request as _req
    payload = json.dumps({
        "from": "Bob Rikh <onboarding@resend.dev>",
        "to": [to_email],
        "reply_to": EMAIL,
        "subject": subject,
        "html": html,
        "text": PLAIN_TEMPLATE,
    }).encode()
    req = _req.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {RESEND_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with _req.urlopen(req, timeout=15) as r:
            return r.status in (200, 201)
    except Exception as e:
        print(f'  ❌ Resend failed to {to_email}: {e}')
        return False


def _send_via_smtp(to_email, subject, html) -> bool:
    """Fallback: send via Gmail SMTP."""
    if not GMAIL_APP_PASSWORD:
        print(f'  ⚠️  No GMAIL_APP_PASSWORD — skipping {to_email}')
        return False
    msg = MIMEMultipart('alternative')
    msg['From'] = f'Bob Rikh <{EMAIL}>'
    msg['To'] = to_email
    msg['Subject'] = subject
    msg['Reply-To'] = EMAIL
    msg.attach(MIMEText(PLAIN_TEMPLATE, 'plain'))
    msg.attach(MIMEText(html, 'html'))
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls()
            s.login(EMAIL, GMAIL_APP_PASSWORD)
            s.send_message(msg)
        return True
    except Exception as e:
        print(f'  ❌ SMTP failed to {to_email}: {e}')
        return False


# ── Send email — Gmail SMTP for recruiter outreach, Resend for self-reports only ──
def send_outreach(to_email, subject, html):
    """Send outreach email. Uses Gmail SMTP (sends from your real address).
    Resend only works for sending to yourself (onboarding@resend.dev limitation).
    """
    # Verify email is deliverable before wasting a send
    verification = verify_email_smtp(to_email)
    if verification is False:
        print(f'  ⚠️  Email undeliverable (MX rejected): {to_email}')
        return False
    # Send via Gmail SMTP (from your real email — recruiters can reply)
    if GMAIL_APP_PASSWORD:
        return _send_via_smtp(to_email, subject, html)
    # Fallback: Resend (only works for sending to yourself)
    if RESEND_KEY:
        return _send_via_resend(to_email, subject, html)
    print(f'  ⚠️  No email credentials configured — cannot send')
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

            # US-RELEVANCE FILTER (Bobur: target REAL US recruiters, skip offshore C2C
            # bench-sales spam). Business signals only — not national origin. Blocks only
            # when clearly a body-shop (2+ negative signals + below threshold).
            ok_us, us_score, us_reasons = passes_us_filter(email, company, desc)
            if not ok_us:
                print(f'  🌍 skip non-US-relevant (score={us_score} {",".join(us_reasons)}): {email}')
                continue

            # Mandatory mailbox check — block only addresses the mail server
            # explicitly REJECTS (False). Allow verified (True) and unverifiable
            # (None, e.g. port 25 blocked on the runner) so real recruiters still
            # get contacted, but dead/guessed domains are stopped.
            # Hunter.io verify FIRST (reliable, handles catch-all); SMTP as backup.
            hv = hunter_verify_email(email)
            if hv is False:
                print(f'  🚫 Hunter says invalid/disposable — skip: {email}')
                continue
            smtp_status = verify_email_smtp(email)
            if smtp_status is False:
                print(f'  🚫 SMTP rejected — skip dead mailbox: {email}')
                continue

            subject, html = build_outreach_email(recruiter_name, title, company)
            print(f'  📧 Sending to {email} for "{title}" @ {company}...')

            if send_outreach(email, subject, html):
                contacted[eh] = {
                    'email': email, 'date': datetime.now().isoformat(),
                    'job': title, 'company': company, 'url': url,
                    'recruiter': recruiter_name,
                    'smtp_verified': smtp_status is True,
                    'us_score': us_score, 'us_reasons': us_reasons,
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


# ── Follow-up emails (3 days after first contact, max 1 follow-up per person) ──
def build_followup_email(recruiter_name, job_title, company):
    name = recruiter_name or ''
    first = name.split()[0] if name else ''
    greeting = f'Hi {first},' if first else 'Hello,'

    html = f"""<div style="font-family:Arial,sans-serif;font-size:14px;color:#333">
<p>{greeting}</p>

<p>I wanted to follow up on my previous email regarding the <strong>{job_title}</strong> position at <strong>{company}</strong>.</p>

<p>I understand you're busy, so I'll keep this brief — I'm still very interested in this opportunity and available to start immediately on a <strong>C2C / Corp-to-Corp</strong> basis.</p>

<p>Would you have 15 minutes this week for a quick call? Happy to work around your schedule.</p>

<br>
{SIGNATURE_HTML}
</div>"""

    subject = f'Re: {job_title} — C2C Available — Bob Rikh'
    return subject, html


def build_followup2_email(recruiter_name, job_title, company):
    name = recruiter_name or ''
    first = name.split()[0] if name else ''
    greeting = f'Hi {first},' if first else 'Hello,'

    html = f"""<div style="font-family:Arial,sans-serif;font-size:14px;color:#333">
<p>{greeting}</p>

<p>Circling back one more time on the <strong>{job_title}</strong> opportunity at <strong>{company}</strong>.</p>

<p>I realize I may have reached the wrong person — if so, could you point me to the right contact on your team?</p>

<p>If you are the right contact, I'd love a quick 10-minute chat. Available immediately for <strong>C2C / Corp-to-Corp</strong>, no sponsorship needed.</p>

<br>
{SIGNATURE_HTML}
</div>"""

    subject = f'Re: {job_title} — quick question / Bob Rikh'
    return subject, html


def build_breakup_email(recruiter_name, job_title, company):
    name = recruiter_name or ''
    first = name.split()[0] if name else ''
    greeting = f'Hi {first},' if first else 'Hello,'

    html = f"""<div style="font-family:Arial,sans-serif;font-size:14px;color:#333">
<p>{greeting}</p>

<p>I've sent a couple of notes about <strong>{job_title}</strong> at <strong>{company}</strong> but haven't heard back — totally understandable, I know inboxes are busy.</p>

<p>Should I close this out on my end, or is the timing just not right?</p>

<p>Either way, best of luck with the search.</p>

<br>
{SIGNATURE_HTML}
</div>"""

    subject = f'Should I close this out? — {job_title} / Bob Rikh'
    return subject, html


def build_reengage_email(recruiter_name, job_title, company):
    name = recruiter_name or ''
    first = name.split()[0] if name else ''
    greeting = f'Hi {first},' if first else 'Hello,'

    html = f"""<div style="font-family:Arial,sans-serif;font-size:14px;color:#333">
<p>{greeting}</p>

<p>I noticed <strong>{company}</strong> has a new <strong>{job_title}</strong> posting and wanted to reconnect.</p>

<p>I'm still available for <strong>C2C / Corp-to-Corp</strong> and my background remains a strong fit — Java 17, Spring Boot, Kafka, Kubernetes, AWS, 8+ years experience.</p>

<p>Would it be worth a quick conversation?</p>

<br>
{SIGNATURE_HTML}
</div>"""

    subject = f'{job_title} at {company} — Bob Rikh (Java C2C)'
    return subject, html


def send_followups():
    """Multi-touch follow-up sequence: day 3 (touch 1), day 7 (touch 2), day 14 (break-up)."""
    contacted = load_contacted()
    now = datetime.now()
    sent = 0
    MAX_FOLLOWUPS = 10

    for key, info in contacted.items():
        if sent >= MAX_FOLLOWUPS:
            break

        if info.get('replied') or info.get('bounced'):
            continue

        email = info.get('email', '')
        job = info.get('job', '')
        company = info.get('company', '')
        recruiter = info.get('recruiter', '')

        if not email or not job:
            continue

        # Skip stored junk/non-person addresses (e.g. scraped 'origin.allow@',
        # 'info@', 'noreply@') that were saved before validation was added.
        if not _looks_like_person_email(email.split('@')[0]):
            print(f'  🚫 skip invalid stored email: {email}')
            info['bounced'] = True  # mark so it is never retried
            contacted[key] = info
            continue

        try:
            contact_date = datetime.fromisoformat(info['date'])
            days_since = (now - contact_date).days
        except Exception:
            continue

        touch1 = info.get('followed_up', False)
        touch2 = info.get('touch2_sent', False)
        touch3 = info.get('touch3_sent', False)

        if not touch1 and 3 <= days_since <= 6:
            subject, html = build_followup_email(recruiter, job, company)
            tag = 'Touch 2 (follow-up)'
        elif touch1 and not touch2 and 7 <= days_since <= 13:
            subject, html = build_followup2_email(recruiter, job, company)
            tag = 'Touch 3 (different angle)'
        elif touch2 and not touch3 and 14 <= days_since <= 30:
            subject, html = build_breakup_email(recruiter, job, company)
            tag = 'Touch 4 (break-up)'
        else:
            continue

        print(f'  📧 {tag} → {email} ({days_since}d) "{job}" @ {company}...')

        if send_outreach(email, subject, html):
            info['last_contact'] = now.isoformat()
            if not touch1:
                info['followed_up'] = True
                info['followup_date'] = now.isoformat()
            elif not touch2:
                info['touch2_sent'] = True
            else:
                info['touch3_sent'] = True
            contacted[key] = info
            sent += 1
            print(f'  ✅ Sent! ({sent}/{MAX_FOLLOWUPS})')

    save_contacted(contacted)
    print(f'📬 Follow-ups: {sent} sent')
    return sent


def send_reengagements():
    """Re-engage contacts 90+ days after last touch (max 3 re-engagements, stop if replied)."""
    contacted = load_contacted()
    now = datetime.now()
    sent = 0
    MAX_REENGAGEMENTS = 5

    # Load today's jobs so we can reference a new opening per company
    current_jobs: dict[str, str] = {}
    if os.path.exists('found_jobs.json'):
        try:
            with open('found_jobs.json') as f:
                data = json.load(f)
            jobs = data if isinstance(data, list) else data.get('jobs', [])
            for j in jobs:
                company_key = j.get('company', '').lower().strip()
                if company_key:
                    current_jobs[company_key] = j.get('title', 'Java Developer')
        except Exception:
            pass

    for key, info in contacted.items():
        if sent >= MAX_REENGAGEMENTS:
            break

        if info.get('replied') or info.get('bounced'):
            continue
        if info.get('re_engage_count', 0) >= 3:
            continue

        last_contact_str = info.get('last_contact') or info.get('date', '')
        if not last_contact_str:
            continue

        try:
            last_contact = datetime.fromisoformat(last_contact_str)
            days_since = (now - last_contact).days
        except Exception:
            continue

        if days_since < 90:
            continue

        email = info.get('email', '')
        company = info.get('company', '')
        recruiter = info.get('recruiter', '')

        if not email or not company:
            continue

        # Only re-engage if there is a current job at this company to reference
        job_title = current_jobs.get(company.lower().strip(), '')
        if not job_title:
            continue

        subject, html = build_reengage_email(recruiter, job_title, company)
        print(f'  📧 Re-engage ({days_since}d) → {email} @ {company} re: "{job_title}"...')

        if send_outreach(email, subject, html):
            info['last_contact'] = now.isoformat()
            info['re_engage_count'] = info.get('re_engage_count', 0) + 1
            contacted[key] = info
            sent += 1
            print(f'  ✅ Re-engage sent! ({sent}/{MAX_REENGAGEMENTS})')

    save_contacted(contacted)
    print(f'🔄 Re-engagements: {sent} sent')
    return sent
