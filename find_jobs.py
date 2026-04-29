#!/usr/bin/env python3
"""
Bob Rikh — Cloud C2C Job Finder v3
Sources: Indeed + LinkedIn + Google + Vendor sites + Google Groups
Keywords: dynamically built from CV skills
"""
import json, os, hashlib, re, sys, urllib.request, ssl, subprocess, tempfile
from datetime import datetime
from jobspy import scrape_jobs
import pandas as pd

EMAIL = 'bobrikh75@gmail.com'
RESEND_KEY = os.environ.get('RESEND_KEY', '')
SEEN_FILE = 'seen_jobs.json'

# ── CV Skills (used for matching AND dynamic search generation) ──
CORE_SKILLS = ['Java', 'Spring Boot', 'Kafka', 'Kubernetes', 'Microservices',
               'Docker', 'AWS', 'GraphQL', 'MongoDB', 'REST API']
ALL_SKILLS = {
    'java','java 17','core java','spring boot','spring mvc','spring data','spring security',
    'spring aop','spring cloud','spring','microservices','rest','restful','rest api','api',
    'kafka','apache kafka','kubernetes','docker','aws','postgresql','postgres','mongodb',
    'cassandra','oracle','sql','mysql','nosql','redis','graphql','hibernate','jpa','maven',
    'gradle','jenkins','ci/cd','git','github','jira','confluence','junit','junit 5','mockito',
    'selenium','cypress','cucumber','tdd','bdd','agile','scrum','oauth2','jwt','keycloak',
    'angular','react','javascript','typescript','json','swagger','postman','splunk','datadog',
    'oop','object-oriented','solid','event-driven','api gateway','web services','tomcat',
    'linux','terraform','lambda','elasticsearch','rabbitmq','devops','yaml','xml',
    'design patterns','multithreading','dependency injection','automated tests',
    'copilot','amazon q','kiro','c2c','corp-to-corp','green card',
}

# ── C2C Vendors (staffing agencies that post C2C jobs) ──
VENDORS = [
    'Skiltrek', 'Pyramid Consulting', 'Collabera', 'TEKsystems', 'Mastech',
    'RIT Solutions', 'Amerit Consulting', 'Han IT Staffing', 'XL Impex', 'Atika Tech',
    'Wipro', 'Infosys', 'TCS', 'HCL', 'Cognizant', 'Mphasis', 'Mindtree',
    'Syntel', 'Hexaware', 'NIIT Technologies', 'Cyient', 'Zensar',
    'Randstad', 'Robert Half', 'Insight Global', 'Kforce', 'Modis',
    'Multivision', 'WorkNovas', 'KAnand', 'Vinsari', 'QTech',
]

# ── Google Groups with C2C postings ──
GOOGLE_GROUPS = [
    'c2chotlist-requirement-posting',
    'only-c2c-req',
    'c2c-w2--requirements',
    'C2C-Corp2Corp-Jobs',
    'job-bank',
]

# ── Dynamic searches: built from CV skills + C2C terms + vendors ──
def build_searches():
    searches = [
        # Core C2C searches
        {'term': 'Java Spring Boot C2C contract', 'location': 'USA'},
        {'term': 'Java developer "corp to corp" contract', 'location': 'USA'},
        {'term': 'Java Spring Boot contract remote', 'location': 'Colorado'},
        {'term': 'Java Kafka Kubernetes contract', 'location': 'USA'},
        {'term': 'Java microservices contract remote', 'location': 'USA'},
        {'term': 'Java backend developer contract', 'location': 'Colorado'},
        # Vendor-specific searches
        {'term': 'Java Spring Boot contract Collabera OR TEKsystems OR Skiltrek', 'location': 'USA'},
        {'term': 'Java developer contract Pyramid OR Mastech OR Kforce', 'location': 'USA'},
        {'term': 'Java C2C contract Randstad OR "Insight Global" OR "Robert Half"', 'location': 'USA'},
        # Skill combo searches (dynamic from CV)
        {'term': 'Java GraphQL MongoDB contract remote', 'location': 'USA'},
        {'term': 'Java AWS Docker Kubernetes contract', 'location': 'USA'},
        {'term': 'Java Spring Boot Redis PostgreSQL contract', 'location': 'USA'},
    ]
    return searches

# ── Scrape Google Groups for C2C postings ──
def search_google_groups():
    """Search C2C Google Groups for Java postings via Google search."""
    results = []
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

    for group in GOOGLE_GROUPS:
        url = f'https://www.google.com/search?q=site:groups.google.com/g/{group}+Java+Spring+Boot+C2C&tbs=qdr:w'
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
                html = r.read().decode('utf-8', errors='ignore')
            # Extract links to group posts
            links = re.findall(r'https://groups\.google\.com/g/[^"&\s]+', html)
            for link in set(links):
                if '/c/' in link:  # actual thread links
                    results.append({
                        'title': f'C2C Posting — {group}',
                        'company': group,
                        'location': 'Remote / Various',
                        'job_url': link,
                        'site': 'google_groups',
                        'description': 'C2C Java posting from Google Groups',
                    })
            if links:
                print(f'  ✅ Google Group "{group}" → {len([l for l in links if "/c/" in l])} threads')
        except Exception as e:
            print(f'  ⚠️  Group "{group}" → {e}')
    return results

# ── Scrape vendor career pages via Google ──
def search_vendors():
    """Search for Java C2C jobs posted by known vendors via Google."""
    results = []
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

    # Batch vendors into groups of 3 for Google searches
    vendor_groups = [VENDORS[i:i+3] for i in range(0, len(VENDORS), 3)]
    for vg in vendor_groups[:5]:  # limit to 5 searches to avoid rate limiting
        query = ' OR '.join(f'"{v}"' for v in vg)
        url = f'https://www.google.com/search?q={urllib.request.quote(f"Java Spring Boot C2C contract {query}")}&tbs=qdr:w&num=10'
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
                html = r.read().decode('utf-8', errors='ignore')
            # Extract job board links
            links = re.findall(r'https?://(?:www\.)?(?:dice|indeed|linkedin|ziprecruiter|glassdoor)\.[a-z]+/[^"&\s<>]+', html)
            for link in set(links):
                results.append({
                    'title': f'Java C2C via {"/".join(vg)}',
                    'company': '/'.join(vg),
                    'location': 'Various',
                    'job_url': link,
                    'site': 'vendor_search',
                    'description': f'C2C job found via vendor search: {", ".join(vg)}',
                })
        except:
            pass
    if results:
        print(f'  ✅ Vendor search → {len(results)} links')
    return results

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            data = json.load(f)
        cutoff = datetime.now().timestamp() - 30 * 86400
        return {k: v for k, v in data.items()
                if datetime.fromisoformat(v.get('date', datetime.now().isoformat())).timestamp() > cutoff}
    return {}

def save_seen(seen):
    with open(SEEN_FILE, 'w') as f: json.dump(seen, f)

def job_hash(url): return hashlib.md5(url.encode()).hexdigest()[:12]

def is_relevant(title, desc):
    combined = (str(title or '') + ' ' + str(desc or '')).lower()
    if 'java' not in combined: return False
    for skip in ['sales only', 'data entry', 'intern ', 'marketing']:
        if skip in str(title or '').lower(): return False
    return True

def score_job(row):
    score = 0
    combined = (str(row.get('title', '')) + ' ' + str(row.get('description', ''))).lower()
    loc = str(row.get('location', '')).lower()
    company = str(row.get('company', '')).lower()

    # Tech stack match (from CV)
    for kw, pts in [('spring boot',15), ('kafka',10), ('kubernetes',10), ('microservice',10),
                     ('docker',5), ('aws',5), ('graphql',8), ('mongodb',5), ('cassandra',5),
                     ('redis',5), ('rest',3), ('junit',3), ('maven',3), ('postgresql',5),
                     ('hibernate',3), ('jenkins',3), ('ci/cd',3), ('agile',2)]:
        if kw in combined: score += pts

    # C2C / contract signals (HIGHEST weight)
    for kw, pts in [('c2c',20), ('corp-to-corp',20), ('corp to corp',20),
                     ('1099',15), ('contract',8), ('w2',5)]:
        if kw in combined: score += pts

    # Known C2C vendor = strong signal
    for v in VENDORS:
        if v.lower() in company or v.lower() in combined:
            score += 15
            break

    # Location match
    if 'remote' in loc or 'remote' in combined: score += 10
    if 'colorado' in loc or 'denver' in loc or 'parker' in loc: score += 10

    # Green card friendly
    if any(k in combined for k in ['green card', 'no sponsorship', 'gc ', 'usc/gc']): score += 10

    # Rate in range ($55-90/hr)
    mn, mx = row.get('min_amount'), row.get('max_amount')
    if str(row.get('interval', '')) == 'hourly' and mn and mx:
        try:
            if 50 <= float(mx) <= 120: score += 10
        except: pass

    # Google Groups source = likely C2C
    if str(row.get('site', '')) == 'google_groups': score += 15

    return min(score, 100)

def search_all():
    all_jobs = pd.DataFrame()
    searches = build_searches()

    # 1. JobSpy: Indeed + LinkedIn + Google
    for s in searches:
        try:
            jobs = scrape_jobs(
                site_name=['indeed', 'linkedin', 'google'],
                search_term=s['term'],
                google_search_term=s['term'] + ' jobs',
                location=s['location'],
                results_wanted=15,
                hours_old=336,
                country_indeed='USA',
                verbose=0,
            )
            if len(jobs) > 0:
                all_jobs = pd.concat([all_jobs, jobs], ignore_index=True)
                print(f'  ✅ "{s["term"][:50]}" → {len(jobs)} jobs')
        except Exception as e:
            print(f'  ❌ "{s["term"][:50]}" → {e}')

    # 2. Google Groups C2C feeds
    print('\n📢 Searching C2C Google Groups...')
    group_jobs = search_google_groups()
    if group_jobs:
        all_jobs = pd.concat([all_jobs, pd.DataFrame(group_jobs)], ignore_index=True)

    # 3. Vendor career page search
    print('\n🏢 Searching vendor postings...')
    vendor_jobs = search_vendors()
    if vendor_jobs:
        all_jobs = pd.concat([all_jobs, pd.DataFrame(vendor_jobs)], ignore_index=True)

    if len(all_jobs) > 0:
        all_jobs = all_jobs.drop_duplicates(subset='job_url')
    return all_jobs

def build_email(scored_jobs, total):
    today = datetime.now().strftime('%A, %B %d %Y')
    rows = ''
    for _, j in scored_jobs.head(30).iterrows():
        rate = ''
        if pd.notna(j.get('min_amount')) and pd.notna(j.get('max_amount')):
            try: rate = f"${int(j['min_amount'])}-${int(j['max_amount'])}/{str(j.get('interval','')) or '?'}"
            except: pass
        bg = '#f0fff0' if j['score'] >= 50 else '#f8f9fa' if j['score'] >= 30 else 'white'
        badge = '🔥' if j['score'] >= 50 else '✅' if j['score'] >= 30 else '📋'
        c2c_tag = ' <span style="background:#34a853;color:white;padding:1px 5px;border-radius:3px;font-size:10px">C2C</span>' if j.get('is_c2c') else ''
        src = str(j.get('site', ''))
        src_badge = {'google_groups': '📢', 'vendor_search': '🏢'}.get(src, '🌐')
        rows += f'''<tr style="background:{bg}">
<td style="padding:8px 10px;font-size:13px">
{badge} <strong>{j['title']}</strong>{c2c_tag}<br>
<span style="color:#666">{src_badge} {j.get('company','?')} | {j.get('location','?')}</span>
{f'<br><b style="color:#1a73e8">{rate}</b>' if rate else ''}
<br><span style="color:#888;font-size:11px">Match: {j["score"]}% | {src}</span>
</td>
<td style="padding:8px;text-align:center;vertical-align:middle">
<a href="{j['job_url']}" style="color:white;background:#1a73e8;padding:8px 12px;border-radius:4px;text-decoration:none;font-size:12px;font-weight:bold">View&nbsp;→</a>
</td></tr>'''

    groups_html = ''.join(f'<li><a href="https://groups.google.com/g/{g}">{g}</a></li>' for g in GOOGLE_GROUPS)
    vendors_html = ', '.join(VENDORS[:15])

    return f'''<html><body style="font-family:Helvetica,Arial,sans-serif;font-size:14px;color:#333;max-width:700px;margin:0 auto">
<div style="background:linear-gradient(135deg,#1a73e8,#34a853);color:white;padding:20px;border-radius:8px 8px 0 0">
<h2 style="margin:0">🔍 {len(scored_jobs)} C2C Java Jobs — Ranked</h2>
<p style="margin:5px 0 0;opacity:0.9">{today}</p>
<p style="margin:3px 0 0;opacity:0.8;font-size:12px">Searched {total} listings | Indeed + LinkedIn + Google + C2C Groups + Vendors</p>
</div>
<div style="padding:15px 20px;border:1px solid #ddd">
<p style="font-size:12px;color:#666">🔥 50%+ | ✅ 30%+ | 📋 check | <span style="background:#34a853;color:white;padding:1px 5px;border-radius:3px;font-size:10px">C2C</span> confirmed | 📢 Google Group | 🏢 Vendor</p>
<table style="border-collapse:collapse;width:100%" border="1" bordercolor="#ddd">
<tr style="background:#1a73e8;color:white"><th style="padding:8px;text-align:left">Job</th><th style="padding:8px;width:60px">Link</th></tr>
{rows}
</table>
<h3 style="margin-top:20px">📢 C2C Google Groups</h3>
<ul style="font-size:13px">{groups_html}</ul>
<h3>🏢 Tracked Vendors</h3>
<p style="font-size:12px;color:#666">{vendors_html}</p>
<h3>🔗 Job Boards</h3>
<ul style="font-size:13px">
<li><a href="https://www.indeed.com/q-c2c-java-developer-jobs.html">Indeed C2C Java</a></li>
<li><a href="https://www.ziprecruiter.com/Jobs/JAVA-C2C">ZipRecruiter Java C2C</a></li>
<li><a href="https://www.dice.com/jobs/q-Java+C2C+contract-l-Remote-jobs">Dice Java C2C</a></li>
</ul>
</div>
<div style="padding:10px 20px;background:#f8f9fa;border-radius:0 0 8px 8px;border:1px solid #ddd;border-top:0">
<p style="color:#666;font-size:11px;margin:0">Cloud Job Finder v3 — Bob Rikh | Skills: {", ".join(CORE_SKILLS)} | {len(VENDORS)} vendors tracked</p>
</div></body></html>'''

def send_email(html, count):
    if not RESEND_KEY:
        print('⚠️  No RESEND_KEY — skipping email')
        return False
    short = datetime.now().strftime('%b %d')
    payload = json.dumps({
        'from': 'Job Finder <onboarding@resend.dev>',
        'to': [EMAIL],
        'subject': f'🔍 {count} C2C Java Jobs — {short}',
        'html': html,
    })
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write(payload)
        tmp = f.name
    try:
        r = subprocess.run(['curl', '-s', '-X', 'POST', 'https://api.resend.com/emails',
            '-H', f'Authorization: Bearer {RESEND_KEY}', '-H', 'Content-Type: application/json',
            '-d', f'@{tmp}'], capture_output=True, text=True, timeout=30)
        os.unlink(tmp)
        print(f'Resend: {r.stdout}')
        return '"id"' in r.stdout
    except Exception as e:
        print(f'Email error: {e}')
        return False

def main():
    print(f'🔍 C2C Job Finder v3 — {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print(f'   Skills: {", ".join(CORE_SKILLS)}')
    print(f'   Vendors: {len(VENDORS)} tracked')
    print(f'   Groups: {len(GOOGLE_GROUPS)} monitored')
    seen = load_seen()
    print(f'   Seen: {len(seen)} jobs\n')

    all_jobs = search_all()
    if len(all_jobs) == 0:
        print('No jobs found.')
        return

    results = []
    for _, row in all_jobs.iterrows():
        url = str(row.get('job_url', ''))
        if not url or job_hash(url) in seen: continue
        if not is_relevant(row.get('title'), row.get('description')): continue
        d = row.to_dict()
        d['score'] = score_job(row)
        d['is_c2c'] = any(k in str(row.get('description', '')).lower()
                          for k in ['c2c', 'corp-to-corp', 'corp to corp', '1099'])
        results.append(d)

    # Mark all as seen
    for _, j in all_jobs.iterrows():
        url = str(j.get('job_url', ''))
        if url:
            seen[job_hash(url)] = {'date': datetime.now().isoformat(), 'title': str(j.get('title', ''))}
    save_seen(seen)

    if not results:
        print(f'No new relevant jobs (searched {len(all_jobs)} total)')
        return

    df = pd.DataFrame(results).sort_values('score', ascending=False)
    print(f'\n🎯 {len(df)} new Java jobs (top 15):')
    for _, j in df.head(15).iterrows():
        badge = '🔥' if j['score'] >= 50 else '✅' if j['score'] >= 30 else '📋'
        c2c = ' [C2C]' if j.get('is_c2c') else ''
        print(f"  {badge} {j['score']:3d}% | {j['title']} @ {j.get('company', '?')}{c2c}")

    html = build_email(df, len(all_jobs))
    if send_email(html, len(df)):
        print(f'\n✅ Email sent to {EMAIL} with {len(df)} jobs')
    else:
        print('\n⚠️  Email not sent')

    print(f'📊 {len(df)} new / {len(all_jobs)} searched / {len(seen)} tracked')

if __name__ == '__main__':
    main()
