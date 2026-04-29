#!/usr/bin/env python3
"""
Bob Rikh — Cloud C2C Job Finder
Runs on GitHub Actions daily. Finds Java C2C jobs, ranks them, emails results.
All config via environment variables (GitHub Secrets).
"""
import json, os, hashlib, re, sys, urllib.request
from datetime import datetime
from jobspy import scrape_jobs
import pandas as pd

EMAIL = 'bobrikh75@gmail.com'
RESEND_KEY = os.environ.get('RESEND_KEY', '')
SEEN_FILE = 'seen_jobs.json'

# ── Bob's 109 CV skills ──
MY_SKILLS = {
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

# ── Search queries (edit these to change what jobs you find) ──
SEARCHES = [
    {'term': 'Java Spring Boot developer contract', 'location': 'Colorado'},
    {'term': 'Java developer C2C corp-to-corp', 'location': 'USA'},
    {'term': 'Java microservices Kafka contract remote', 'location': 'USA'},
    {'term': 'Java backend developer contract remote', 'location': 'USA'},
    {'term': '"Java" "Spring Boot" contract', 'location': 'Colorado'},
]

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            data = json.load(f)
        cutoff = (datetime.now().timestamp() - 30*86400)
        return {k:v for k,v in data.items()
                if datetime.fromisoformat(v.get('date',datetime.now().isoformat())).timestamp() > cutoff}
    return {}

def save_seen(seen):
    with open(SEEN_FILE, 'w') as f: json.dump(seen, f)

def job_hash(url): return hashlib.md5(url.encode()).hexdigest()[:12]

def is_relevant(title, desc):
    combined = ((title or '') + ' ' + (desc or '')).lower()
    if 'java' not in combined: return False
    for skip in ['sales only','data entry','intern ','marketing']:
        if skip in (title or '').lower(): return False
    return True

def score_job(row):
    score = 0
    combined = (str(row.get('title','')) + ' ' + str(row.get('description',''))).lower()
    loc = str(row.get('location','')).lower()

    for kw, pts in [('spring boot',15),('kafka',10),('kubernetes',10),('microservice',10),
                     ('docker',5),('aws',5),('graphql',8),('mongodb',5),('cassandra',5),
                     ('redis',5),('rest',3),('junit',3),('maven',3)]:
        if kw in combined: score += pts

    for kw, pts in [('c2c',15),('corp-to-corp',15),('corp to corp',15),('1099',10),('contract',8)]:
        if kw in combined: score += pts

    if 'remote' in loc or 'remote' in combined: score += 10
    if 'colorado' in loc or 'denver' in loc: score += 10
    if any(k in combined for k in ['green card','no sponsorship','gc ']): score += 5

    mn, mx = row.get('min_amount'), row.get('max_amount')
    if str(row.get('interval','')) == 'hourly' and mn and mx:
        if 50 <= float(mx) <= 120: score += 10

    return min(score, 100)

def search_all():
    all_jobs = pd.DataFrame()
    for s in SEARCHES:
        try:
            jobs = scrape_jobs(
                site_name=['indeed','linkedin','zip_recruiter','glassdoor','google'],
                search_term=s['term'],
                google_search_term=s['term'] + ' jobs',
                location=s['location'],
                results_wanted=20,
                hours_old=336,
                country_indeed='USA',
                verbose=0,
            )
            if len(jobs) > 0:
                all_jobs = pd.concat([all_jobs, jobs], ignore_index=True)
                print(f'  ✅ "{s["term"]}" → {len(jobs)} jobs')
        except Exception as e:
            print(f'  ❌ "{s["term"]}" → {e}')
    if len(all_jobs) > 0:
        all_jobs = all_jobs.drop_duplicates(subset='job_url')
    return all_jobs

def build_email(scored_jobs, total):
    today = datetime.now().strftime('%A, %B %d %Y')
    rows = ''
    for _, j in scored_jobs.iterrows():
        rate = ''
        if pd.notna(j.get('min_amount')) and pd.notna(j.get('max_amount')):
            rate = f"${int(j['min_amount'])}-${int(j['max_amount'])}/{str(j.get('interval','')) or '?'}"
        bg = '#f0fff0' if j['score']>=50 else '#f8f9fa' if j['score']>=30 else 'white'
        badge = '🔥' if j['score']>=50 else '✅' if j['score']>=30 else '📋'
        c2c = ' <span style="background:#34a853;color:white;padding:1px 5px;border-radius:3px;font-size:10px">C2C</span>' if j.get('is_c2c') else ''
        rows += f'''<tr style="background:{bg}">
<td style="padding:8px 10px;font-size:13px">
{badge} <strong>{j['title']}</strong>{c2c}<br>
<span style="color:#666">{j.get('company','?')} | {j.get('location','?')}</span>
{f'<br><b style="color:#1a73e8">{rate}</b>' if rate else ''}
<br><span style="color:#888;font-size:11px">Match: {j["score"]}% | {j["site"]}</span>
</td>
<td style="padding:8px;text-align:center;vertical-align:middle">
<a href="{j['job_url']}" style="color:white;background:#1a73e8;padding:8px 12px;border-radius:4px;text-decoration:none;font-size:12px;font-weight:bold">Apply&nbsp;→</a>
</td></tr>'''

    return f'''<html><body style="font-family:Helvetica,Arial,sans-serif;font-size:14px;color:#333;max-width:700px;margin:0 auto">
<div style="background:linear-gradient(135deg,#1a73e8,#34a853);color:white;padding:20px;border-radius:8px 8px 0 0">
<h2 style="margin:0">🔍 {len(scored_jobs)} C2C Java Jobs — Ranked by Match</h2>
<p style="margin:5px 0 0;opacity:0.9">{today}</p>
<p style="margin:3px 0 0;opacity:0.8;font-size:12px">Searched {total} listings | Indeed + ZipRecruiter + Google</p>
</div>
<div style="padding:15px 20px;border:1px solid #ddd">
<p style="font-size:12px;color:#666">🔥 50%+ match | ✅ 30%+ match | 📋 worth checking | <span style="background:#34a853;color:white;padding:1px 5px;border-radius:3px;font-size:10px">C2C</span> = corp-to-corp confirmed</p>
<table style="border-collapse:collapse;width:100%" border="1" bordercolor="#ddd">
<tr style="background:#1a73e8;color:white"><th style="padding:8px 10px;text-align:left">Job</th><th style="padding:8px;width:70px">Apply</th></tr>
{rows}
</table>
<h3 style="margin-top:20px">🔗 Browse More</h3>
<ul style="font-size:13px">
<li><a href="https://www.ziprecruiter.com/Jobs/JAVA-C2C">ZipRecruiter Java C2C</a></li>
<li><a href="https://www.indeed.com/q-c2c-java-developer-jobs.html">Indeed C2C Java</a></li>
<li><a href="https://groups.google.com/g/c2chotlist-requirement-posting">C2C Hotlist Google Group</a></li>
<li><a href="https://groups.google.com/g/only-c2c-req">Only C2C Google Group</a></li>
<li><a href="https://www.dice.com/jobs/q-Java+C2C+contract-l-Remote-jobs">Dice Java C2C</a></li>
</ul>
<div style="background:#fff3cd;padding:10px;border-radius:4px;margin-top:10px;font-size:12px">
<strong>💡 To update search keywords:</strong> Edit SEARCHES list in find_jobs.py and push to GitHub. Changes take effect next run.
</div>
</div>
<div style="padding:10px 20px;background:#f8f9fa;border-radius:0 0 8px 8px;border:1px solid #ddd;border-top:0">
<p style="color:#666;font-size:11px;margin:0">Cloud Job Finder v2 — Bob Rikh | GitHub Actions + JobSpy | Runs daily 9:30 AM MT</p>
</div></body></html>'''

def send_email(html, count):
    if not RESEND_KEY:
        print('⚠️  No RESEND_KEY set — skipping email')
        return False
    short = datetime.now().strftime('%b %d')
    import tempfile, subprocess
    payload = json.dumps({
        'from': 'Job Finder <onboarding@resend.dev>',
        'to': [EMAIL],
        'subject': f'🔍 {count} C2C Java Jobs (Ranked) — {short}',
        'html': html,
    })
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write(payload)
        tmp = f.name
    try:
        r = subprocess.run(['curl','-s','-X','POST','https://api.resend.com/emails',
            '-H',f'Authorization: Bearer {RESEND_KEY}','-H','Content-Type: application/json',
            '-d',f'@{tmp}'], capture_output=True, text=True, timeout=30)
        os.unlink(tmp)
        print(f'Resend: {r.stdout}')
        return '"id"' in r.stdout
    except Exception as e:
        print(f'Email error: {e}')
        return False

def main():
    print(f'🔍 C2C Job Finder — {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    seen = load_seen()
    print(f'   Tracking {len(seen)} seen jobs')

    all_jobs = search_all()
    if len(all_jobs) == 0:
        print('No jobs found.')
        return

    results = []
    for _, row in all_jobs.iterrows():
        url = row.get('job_url', '')
        if not url or job_hash(url) in seen: continue
        if not is_relevant(row.get('title'), row.get('description')): continue
        d = row.to_dict()
        d['score'] = score_job(row)
        d['is_c2c'] = any(k in str(row.get('description','')).lower() for k in ['c2c','corp-to-corp','corp to corp','1099'])
        results.append(d)

    # Mark ALL as seen (including filtered ones)
    for _, j in all_jobs.iterrows():
        url = j.get('job_url', '')
        if url:
            seen[job_hash(url)] = {'date': datetime.now().isoformat(), 'title': str(j.get('title',''))}
    save_seen(seen)

    if not results:
        print(f'No new relevant jobs (searched {len(all_jobs)} total)')
        return

    df = pd.DataFrame(results).sort_values('score', ascending=False)
    print(f'\n🎯 {len(df)} new Java jobs (top 10):')
    for _, j in df.head(10).iterrows():
        badge = '🔥' if j['score']>=50 else '✅' if j['score']>=30 else '📋'
        c2c = ' [C2C]' if j.get('is_c2c') else ''
        print(f"  {badge} {j['score']:3d}% | {j['title']} @ {j.get('company','?')}{c2c}")

    html = build_email(df, len(all_jobs))
    if send_email(html, len(df)):
        print(f'\n✅ Email sent to {EMAIL} with {len(df)} jobs')
    else:
        print('\n⚠️  Email not sent (no password configured)')

    print(f'📊 {len(df)} new / {len(all_jobs)} searched / {len(seen)} tracked')

if __name__ == '__main__':
    main()
