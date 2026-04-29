#!/usr/bin/env python3
"""
Bob Rikh — Cloud C2C Job Finder v4 (Self-Learning)
- Dynamically discovers new vendors from job postings → searches them next run
- Dynamically discovers new keywords from postings → adds to search queries
- Searches: Indeed, LinkedIn, Google, Dice (via Google), C2C sites, Google Groups
- Deduplicates by title+company (not just URL)
- Filters fake postings
"""
import json, os, hashlib, re, sys, urllib.request, ssl, subprocess, tempfile
from datetime import datetime
from jobspy import scrape_jobs
import pandas as pd

EMAIL = 'bobrikh75@gmail.com'
RESEND_KEY = os.environ.get('RESEND_KEY', '')
SEEN_FILE = 'seen_jobs.json'
LEARNED_FILE = 'learned.json'  # dynamic vendors + keywords discovered from postings

# ── CV Skills ──
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

# ── Seed vendors (script discovers more dynamically) ──
SEED_VENDORS = [
    'Skiltrek','Pyramid Consulting','Collabera','TEKsystems','Mastech','RIT Solutions',
    'Amerit Consulting','Han IT Staffing','XL Impex','Atika Tech','Randstad',
    'Robert Half','Insight Global','Kforce','Modis','Multivision','WorkNovas',
    'KAnand','Vinsari','QTech','Wipro','Infosys','TCS','HCL','Cognizant',
    'Mphasis','Hexaware','Cyient','Zensar','Syntel','Mindtree',
]

# ── Known C2C staffing patterns (to detect new vendors) ──
VENDOR_SIGNALS = re.compile(
    r'(consulting|staffing|solutions|technologies|tech|infotech|systems|'
    r'corporation|corp|inc\b|llc\b|group|partners|global|services)',
    re.IGNORECASE
)

GOOGLE_GROUPS = [
    'c2chotlist-requirement-posting', 'only-c2c-req',
    'c2c-w2--requirements', 'C2C-Corp2Corp-Jobs', 'job-bank',
]

# ── Fake job signals ──
FAKE_SIGNALS = [
    'click here to apply', 'no company name', 'confidential company',
    'staffing agency hiring for itself', 'test posting',
]

def load_json(path):
    if os.path.exists(path):
        with open(path) as f: return json.load(f)
    return {}

def save_json(path, data):
    with open(path, 'w') as f: json.dump(data, f, indent=2)

def job_hash(url): return hashlib.md5(str(url).encode()).hexdigest()[:12]

def dedup_key(title, company):
    """Dedup by normalized title+company, catches same job posted on multiple boards."""
    t = re.sub(r'[^a-z0-9]', '', str(title).lower())[:40]
    c = re.sub(r'[^a-z0-9]', '', str(company).lower())[:20]
    return hashlib.md5(f'{t}_{c}'.encode()).hexdigest()[:12]

# ══════════════════════════════════════════════════════════════
# DYNAMIC LEARNING — discovers vendors + keywords from postings
# ══════════════════════════════════════════════════════════════

def load_learned():
    data = load_json(LEARNED_FILE)
    return {
        'vendors': set(data.get('vendors', [])),
        'keywords': set(data.get('keywords', [])),
        'updated': data.get('updated', ''),
    }

def save_learned(learned):
    save_json(LEARNED_FILE, {
        'vendors': sorted(learned['vendors']),
        'keywords': sorted(learned['keywords']),
        'updated': datetime.now().isoformat(),
    })

def discover_vendors(jobs_df, known_vendors):
    """Find new vendor/staffing company names from job postings."""
    new_vendors = set()
    known_lower = {v.lower() for v in known_vendors}
    for _, row in jobs_df.iterrows():
        company = str(row.get('company', ''))
        if not company or company == '?' or len(company) < 3: continue
        if company.lower() in known_lower: continue
        desc = str(row.get('description', '')).lower()
        # If posting mentions C2C AND company name looks like a staffing firm
        is_c2c = any(k in desc for k in ['c2c', 'corp-to-corp', 'corp to corp', '1099', 'w2/c2c'])
        is_vendor = bool(VENDOR_SIGNALS.search(company))
        if is_c2c and is_vendor:
            new_vendors.add(company.strip())
    return new_vendors

def discover_keywords(jobs_df):
    """Find new tech keywords appearing in C2C job postings that aren't in CV."""
    keyword_counts = {}
    tech_pattern = re.compile(r'\b((?:[A-Z][a-z]+(?:\.js|\.io)?)|(?:[a-z]+(?:db|mq|sql|js)))\b')
    for _, row in jobs_df.iterrows():
        desc = str(row.get('description', ''))
        if not any(k in desc.lower() for k in ['c2c', 'contract', 'corp']): continue
        words = tech_pattern.findall(desc)
        for w in words:
            wl = w.lower()
            if wl in ALL_SKILLS or len(wl) < 3: continue
            if wl in ('the', 'and', 'for', 'with', 'from', 'this', 'that', 'will', 'are'): continue
            keyword_counts[wl] = keyword_counts.get(wl, 0) + 1
    # Only keep keywords that appear in 3+ postings (real signal, not noise)
    return {k for k, v in keyword_counts.items() if v >= 3}

# ══════════════════════════════════════════════════════════════
# SEARCH
# ══════════════════════════════════════════════════════════════

def build_searches(learned_vendors, learned_keywords):
    searches = [
        # Core C2C
        {'term': 'Java Spring Boot C2C contract remote', 'location': 'USA'},
        {'term': 'Java developer "corp to corp" contract', 'location': 'USA'},
        {'term': 'Java Spring Boot contract', 'location': 'Colorado'},
        {'term': 'Java Kafka Kubernetes contract remote', 'location': 'USA'},
        {'term': 'Java microservices contract remote', 'location': 'USA'},
        {'term': 'Java backend developer contract', 'location': 'Colorado'},
        {'term': 'Java GraphQL MongoDB contract remote', 'location': 'USA'},
        {'term': 'Java AWS Docker Kubernetes contract', 'location': 'USA'},
        # C2C-specific sites via Google
        {'term': 'site:dice.com Java Spring Boot C2C contract', 'location': 'USA'},
    ]
    # Dynamic vendor searches (from learned vendors)
    all_vendors = list(SEED_VENDORS) + list(learned_vendors)
    for i in range(0, min(len(all_vendors), 15), 3):
        batch = all_vendors[i:i+3]
        names = ' OR '.join(f'"{v}"' for v in batch)
        searches.append({'term': f'Java C2C contract {names}', 'location': 'USA'})

    # Dynamic keyword searches (from learned keywords)
    if learned_keywords:
        top_kw = list(learned_keywords)[:5]
        searches.append({'term': f'Java {" ".join(top_kw)} contract C2C', 'location': 'USA'})

    return searches

def search_google_groups():
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
            links = re.findall(r'https://groups\.google\.com/g/[^"&\s]+', html)
            threads = [l for l in set(links) if '/c/' in l]
            for link in threads:
                results.append({
                    'title': f'C2C Posting — {group}', 'company': group,
                    'location': 'Remote / Various', 'job_url': link,
                    'site': 'google_groups', 'description': 'C2C Java posting',
                })
            if threads:
                print(f'  ✅ Group "{group}" → {len(threads)} threads')
        except Exception as e:
            print(f'  ⚠️  Group "{group}" → {e}')
    return results

def search_c2c_sites():
    """Search C2C-specific job sites via Google."""
    results = []
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
    c2c_queries = [
        'site:dice.com "Java" "C2C" OR "corp to corp" contract remote',
        '"Java Spring Boot" "C2C" OR "corp-to-corp" contract developer remote',
    ]
    for q in c2c_queries:
        try:
            url = f'https://www.google.com/search?q={urllib.request.quote(q)}&tbs=qdr:w&num=15'
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
                html = r.read().decode('utf-8', errors='ignore')
            links = re.findall(r'https?://(?:www\.)?(?:dice|indeed|linkedin)\.[a-z]+/[^"&\s<>]+', html)
            for link in set(links):
                results.append({
                    'title': 'C2C Java posting', 'company': '?',
                    'location': 'Various', 'job_url': link,
                    'site': 'c2c_search', 'description': '',
                })
        except: pass
    if results:
        print(f'  ✅ C2C site search → {len(results)} links')
    return results

# ══════════════════════════════════════════════════════════════
# SCORING + FILTERING
# ══════════════════════════════════════════════════════════════

def is_fake(title, desc, company):
    t = str(title or '').lower()
    d = str(desc or '').lower()
    c = str(company or '').lower()
    # No Java = irrelevant
    if 'java' not in t + ' ' + d: return True
    # Skip non-dev roles
    if any(s in t for s in ['sales only', 'data entry', 'intern ', 'marketing', 'recruiter']): return True
    # No company = likely fake
    if not c or c in ('?', 'nan', 'none', 'confidential', 'confidential company'): return True
    # Fake signals in description
    if any(f in d for f in FAKE_SIGNALS): return True
    return False

def score_job(row, all_vendors):
    score = 0
    combined = (str(row.get('title', '')) + ' ' + str(row.get('description', ''))).lower()
    loc = str(row.get('location', '')).lower()
    company = str(row.get('company', '')).lower()

    # Tech match
    for kw, pts in [('spring boot',15), ('kafka',10), ('kubernetes',10), ('microservice',10),
                     ('docker',5), ('aws',5), ('graphql',8), ('mongodb',5), ('cassandra',5),
                     ('redis',5), ('rest',3), ('junit',3), ('maven',3), ('postgresql',5),
                     ('hibernate',3), ('jenkins',3), ('ci/cd',3)]:
        if kw in combined: score += pts

    # C2C signals (highest weight)
    for kw, pts in [('c2c',20), ('corp-to-corp',20), ('corp to corp',20),
                     ('1099',15), ('w2/c2c',15), ('contract',8)]:
        if kw in combined: score += pts

    # Known vendor = real C2C
    for v in all_vendors:
        if v.lower() in company or v.lower() in combined:
            score += 15; break

    # Location
    if 'remote' in loc or 'remote' in combined: score += 10
    if any(k in loc for k in ['colorado', 'denver', 'parker']): score += 10

    # Green card friendly
    if any(k in combined for k in ['green card', 'no sponsorship', 'usc/gc', 'gc only']): score += 10

    # Rate in range
    try:
        mn, mx = row.get('min_amount'), row.get('max_amount')
        if str(row.get('interval', '')) == 'hourly' and mn and mx:
            if 50 <= float(mx) <= 120: score += 10
    except: pass

    # Google Groups = likely real C2C
    if str(row.get('site', '')) == 'google_groups': score += 15

    return min(score, 100)

# ══════════════════════════════════════════════════════════════
# DEDUP
# ══════════════════════════════════════════════════════════════

def deduplicate(df):
    """Remove duplicates by URL AND by title+company similarity."""
    if len(df) == 0: return df
    # First: exact URL dedup
    df = df.drop_duplicates(subset='job_url')
    # Second: title+company dedup (same job on multiple boards)
    df['_dedup'] = df.apply(lambda r: dedup_key(r.get('title',''), r.get('company','')), axis=1)
    df = df.drop_duplicates(subset='_dedup')
    df = df.drop(columns=['_dedup'])
    return df

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def search_all(learned):
    all_jobs = pd.DataFrame()
    searches = build_searches(learned['vendors'], learned['keywords'])
    print(f'  Running {len(searches)} search queries...\n')

    for s in searches:
        try:
            jobs = scrape_jobs(
                site_name=['indeed', 'linkedin', 'google'],
                search_term=s['term'], google_search_term=s['term'] + ' jobs',
                location=s['location'], results_wanted=15,
                hours_old=336, country_indeed='USA', verbose=0,
            )
            if len(jobs) > 0:
                all_jobs = pd.concat([all_jobs, jobs], ignore_index=True)
                print(f'  ✅ "{s["term"][:55]}" → {len(jobs)}')
        except Exception as e:
            print(f'  ❌ "{s["term"][:55]}" → {e}')

    print('\n📢 C2C Google Groups...')
    for j in search_google_groups():
        all_jobs = pd.concat([all_jobs, pd.DataFrame([j])], ignore_index=True)

    print('\n🔍 C2C-specific searches...')
    for j in search_c2c_sites():
        all_jobs = pd.concat([all_jobs, pd.DataFrame([j])], ignore_index=True)

    return deduplicate(all_jobs) if len(all_jobs) > 0 else all_jobs

def build_email(scored_jobs, total, learned):
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
        src_icon = {'google_groups': '📢', 'c2c_search': '🎯'}.get(src, '🌐')
        rows += f'''<tr style="background:{bg}"><td style="padding:8px 10px;font-size:13px">
{badge} <strong>{j['title']}</strong>{c2c_tag}<br>
<span style="color:#666">{src_icon} {j.get('company','?')} | {j.get('location','?')}</span>
{f'<br><b style="color:#1a73e8">{rate}</b>' if rate else ''}
<br><span style="color:#888;font-size:11px">Match: {j["score"]}% | {src}</span>
</td><td style="padding:8px;text-align:center;vertical-align:middle">
<a href="{j['job_url']}" style="color:white;background:#1a73e8;padding:8px 12px;border-radius:4px;text-decoration:none;font-size:12px;font-weight:bold">View→</a>
</td></tr>'''

    groups_html = ''.join(f'<li><a href="https://groups.google.com/g/{g}">{g}</a></li>' for g in GOOGLE_GROUPS)
    n_vendors = len(SEED_VENDORS) + len(learned['vendors'])
    n_kw = len(learned['keywords'])

    return f'''<html><body style="font-family:Helvetica,Arial,sans-serif;font-size:14px;color:#333;max-width:700px;margin:0 auto">
<div style="background:linear-gradient(135deg,#1a73e8,#34a853);color:white;padding:20px;border-radius:8px 8px 0 0">
<h2 style="margin:0">🔍 {len(scored_jobs)} C2C Java Jobs — Ranked</h2>
<p style="margin:5px 0 0;opacity:0.9">{today}</p>
<p style="margin:3px 0 0;opacity:0.8;font-size:12px">{total} searched | {n_vendors} vendors | {n_kw} learned keywords | Indeed+LinkedIn+Google+Groups</p>
</div>
<div style="padding:15px 20px;border:1px solid #ddd">
<p style="font-size:11px;color:#666">🔥 50%+ | ✅ 30%+ | 📋 check | <span style="background:#34a853;color:white;padding:1px 5px;border-radius:3px;font-size:10px">C2C</span> confirmed | 📢 Group | 🎯 C2C site</p>
<table style="border-collapse:collapse;width:100%" border="1" bordercolor="#ddd">
<tr style="background:#1a73e8;color:white"><th style="padding:8px;text-align:left">Job</th><th style="padding:8px;width:55px">Link</th></tr>
{rows}</table>
<h3 style="margin-top:15px;font-size:14px">📢 C2C Groups</h3><ul style="font-size:12px">{groups_html}</ul>
<h3 style="font-size:14px">🔗 Browse</h3>
<ul style="font-size:12px">
<li><a href="https://www.dice.com/jobs/q-Java+C2C+contract-l-Remote-jobs">Dice C2C</a></li>
<li><a href="https://www.indeed.com/q-c2c-java-developer-jobs.html">Indeed C2C</a></li>
<li><a href="https://www.ziprecruiter.com/Jobs/JAVA-C2C">ZipRecruiter C2C</a></li></ul>
{f'<p style="font-size:11px;color:#888">🧠 Learned {len(learned["vendors"])} new vendors + {n_kw} keywords from past postings</p>' if learned["vendors"] else ''}
</div>
<div style="padding:8px 20px;background:#f8f9fa;border-radius:0 0 8px 8px;border:1px solid #ddd;border-top:0">
<p style="color:#666;font-size:10px;margin:0">Job Finder v4 (self-learning) — Bob Rikh | Runs daily 9:30 AM MT</p>
</div></body></html>'''

def send_email(html, count):
    if not RESEND_KEY:
        print('⚠️  No RESEND_KEY'); return False
    short = datetime.now().strftime('%b %d')
    payload = json.dumps({
        'from': 'Job Finder <onboarding@resend.dev>', 'to': [EMAIL],
        'subject': f'🔍 {count} C2C Java Jobs — {short}', 'html': html,
    })
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write(payload); tmp = f.name
    try:
        r = subprocess.run(['curl', '-s', '-X', 'POST', 'https://api.resend.com/emails',
            '-H', f'Authorization: Bearer {RESEND_KEY}', '-H', 'Content-Type: application/json',
            '-d', f'@{tmp}'], capture_output=True, text=True, timeout=30)
        os.unlink(tmp)
        print(f'Resend: {r.stdout}')
        return '"id"' in r.stdout
    except Exception as e:
        print(f'Email error: {e}'); return False

def main():
    print(f'🔍 C2C Job Finder v4 (self-learning) — {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    seen = load_json(SEEN_FILE)
    # Clean old seen entries
    cutoff = datetime.now().timestamp() - 30 * 86400
    seen = {k: v for k, v in seen.items()
            if datetime.fromisoformat(v.get('date', datetime.now().isoformat())).timestamp() > cutoff}

    learned = load_learned()
    all_vendors = set(SEED_VENDORS) | learned['vendors']
    print(f'  Vendors: {len(all_vendors)} ({len(learned["vendors"])} learned)')
    print(f'  Keywords: {len(learned["keywords"])} learned')
    print(f'  Seen: {len(seen)} jobs\n')

    all_jobs = search_all(learned)
    if len(all_jobs) == 0:
        print('No jobs found.'); return

    # ── LEARN from this batch ──
    new_vendors = discover_vendors(all_jobs, all_vendors)
    new_keywords = discover_keywords(all_jobs)
    if new_vendors:
        learned['vendors'] |= new_vendors
        print(f'\n🧠 Learned {len(new_vendors)} new vendors: {", ".join(new_vendors)}')
    if new_keywords:
        learned['keywords'] |= new_keywords
        print(f'🧠 Learned {len(new_keywords)} new keywords: {", ".join(list(new_keywords)[:10])}')
    save_learned(learned)

    # ── Score + filter ──
    results = []
    seen_dedup = set()
    for _, row in all_jobs.iterrows():
        url = str(row.get('job_url', ''))
        if not url or job_hash(url) in seen: continue
        if is_fake(row.get('title'), row.get('description'), row.get('company')): continue
        dk = dedup_key(row.get('title', ''), row.get('company', ''))
        if dk in seen_dedup: continue
        seen_dedup.add(dk)
        d = row.to_dict()
        d['score'] = score_job(row, all_vendors | learned['vendors'])
        d['is_c2c'] = any(k in str(row.get('description', '')).lower()
                          for k in ['c2c', 'corp-to-corp', 'corp to corp', '1099', 'w2/c2c'])
        results.append(d)

    # Mark all seen
    for _, j in all_jobs.iterrows():
        url = str(j.get('job_url', ''))
        if url: seen[job_hash(url)] = {'date': datetime.now().isoformat(), 'title': str(j.get('title', ''))}
    save_json(SEEN_FILE, seen)

    if not results:
        print(f'No new relevant jobs (searched {len(all_jobs)})'); return

    df = pd.DataFrame(results).sort_values('score', ascending=False)
    print(f'\n🎯 {len(df)} new jobs (top 15):')
    for _, j in df.head(15).iterrows():
        badge = '🔥' if j['score'] >= 50 else '✅' if j['score'] >= 30 else '📋'
        c2c = ' [C2C]' if j.get('is_c2c') else ''
        print(f"  {badge} {j['score']:3d}% | {j['title']} @ {j.get('company', '?')}{c2c}")

    html = build_email(df, len(all_jobs), learned)
    if send_email(html, len(df)):
        print(f'\n✅ Email sent to {EMAIL}')

    # ── Step 2: Auto-outreach to recruiters ──
    if os.environ.get('GMAIL_APP_PASSWORD'):
        print('\n📧 Starting recruiter outreach...')
        from outreach import process_jobs, send_followups
        # Only outreach to high-scoring C2C jobs
        top_jobs = df[df['score'] >= 40].head(20).to_dict('records')
        if top_jobs:
            outreach_results = process_jobs(top_jobs)
            sent = [r for r in outreach_results if r['status'] == 'sent']
            no_email = [r for r in outreach_results if r['status'] == 'no_email']
            print(f'📧 {len(sent)} emails sent to recruiters')
            if no_email:
                print(f'🔍 {len(no_email)} jobs — no email found. LinkedIn search links in daily email.')
        # Follow up on contacts from 3+ days ago
        print('\n📬 Checking for follow-ups...')
        send_followups()
    else:
        print('\n⚠️  No GMAIL_APP_PASSWORD — skipping recruiter outreach')

    print(f'\n📊 {len(df)} new / {len(all_jobs)} searched / {len(seen)} tracked')
    print(f'🧠 {len(learned["vendors"])} learned vendors / {len(learned["keywords"])} learned keywords')

if __name__ == '__main__':
    main()
