#!/usr/bin/env python3
"""
Manual Apply List — Bob Rikh
Every job CI/CD could NOT auto-apply to → goes into a PERSISTENT master file
so you apply them yourself, one by one, WITHOUT MISSING ANY.

Logic (as requested):
  - CI/CD auto-applies where it can (Greenhouse/AI-Agent).
  - Everything it finds but can't/didn't submit → added to the master list.
  - A job NEVER drops off the list until YOU mark it applied.

Files:
  - agent/data/manual_apply_master.csv   ← THE master list (open in Excel/Numbers)
      columns: status,score,title,company,location,rate,c2c,source,url,added
      status = pending | applied | skip   (you edit this column)
  - manual_apply_list.html               ← pretty view of PENDING jobs (browser)
  - emails the pending list (Resend) if RESEND_KEY set

Source: found_jobs.json (all discovered jobs) + already-applied dedup.

Run: python3 manual_apply_list.py
Mark done: edit the CSV, set status to 'applied' (or 'skip'). Applied/skip rows
           stay in the file for your records but drop out of the HTML/email.
"""
import json, os, re, csv, html, subprocess, tempfile
from datetime import datetime

EMAIL = 'bobrikh75@gmail.com'
RESEND_KEY = os.environ.get('RESEND_KEY', '')
RESEND_FROM = os.environ.get('RESEND_FROM', 'Job Finder <onboarding@resend.dev>')

ROOT = '.' if os.path.exists('found_jobs.json') else '..'
FOUND = os.path.join(ROOT, 'found_jobs.json')
MASTER = os.path.join(ROOT, 'agent', 'data', 'manual_apply_master.csv')
OUT_HTML = os.path.join(ROOT, 'manual_apply_list.html')

DEDUP_FILES = [
    os.path.join(ROOT, 'agent', 'data', 'dice_applied_ids.json'),
    os.path.join(ROOT, 'agent', 'data', 'greenhouse_applied.json'),
    os.path.join(ROOT, 'agent', 'data', 'applied_jks.json'),
    os.path.join(ROOT, 'agent', 'data', 'applied_titles.json'),
]
FIELDS = ['status', 'score', 'title', 'company', 'location', 'rate', 'c2c', 'source', 'url', 'added']


def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _norm(s):
    return re.sub(r'[^a-z0-9]', '', str(s).lower())[:40]


def _key(title, company):
    return _norm(title) + '_' + _norm(company)


def _applied_keys():
    keys = set()
    for p in DEDUP_FILES:
        d = _load(p, [])
        items = d if isinstance(d, list) else list(d.keys()) if isinstance(d, dict) else []
        for it in items:
            keys.add(_norm(it))
    return keys


def _load_master():
    """Return dict: key -> row. Preserves your status edits."""
    rows = {}
    if os.path.exists(MASTER):
        with open(MASTER, newline='') as f:
            for r in csv.DictReader(f):
                k = _key(r.get('title', ''), r.get('company', ''))
                rows[k] = r
    return rows


def _save_master(rows):
    os.makedirs(os.path.dirname(MASTER), exist_ok=True)
    with open(MASTER, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        # newest/highest score first for readability
        for r in sorted(rows.values(), key=lambda x: (x.get('status') != 'pending', -int(x.get('score', 0) or 0))):
            w.writerow({k: r.get(k, '') for k in FIELDS})


def main():
    data = _load(FOUND, [])
    jobs = data.get('jobs', data) if isinstance(data, dict) else data
    if not jobs:
        print('No jobs in found_jobs.json'); return

    # ── Pull in misses from Indeed/Greenhouse too (they save to failed_jobs.json) ──
    # so EVERY channel's un-applied jobs land in the manual list, nothing missed.
    failed = _load(os.path.join(ROOT, 'agent', 'data', 'failed_jobs.json'), [])
    for fj in (failed if isinstance(failed, list) else []):
        if isinstance(fj, dict) and fj.get('url') and fj.get('title'):
            u = str(fj['url'])
            if not any(str(j.get('url') or j.get('job_url') or '') == u for j in jobs):
                src = 'indeed' if 'indeed' in u else 'greenhouse' if 'greenhouse' in u else 'ats'
                jobs.append({'title': fj.get('title', ''), 'company': fj.get('company', ''),
                             'url': u, 'location': fj.get('location', ''),
                             'score': int(fj.get('score', 40) or 40),
                             'is_c2c': bool(fj.get('is_c2c')), 'source': src})

    applied = _applied_keys()
    master = _load_master()

    added = 0
    for j in jobs:
        title = str(j.get('title', '')).strip()
        company = str(j.get('company', '')).strip()
        url = str(j.get('url') or j.get('job_url') or j.get('linkedin_url') or '').strip()
        if not title or not url:
            continue
        k = _key(title, company)
        # auto-applied elsewhere → don't add to manual list
        if _norm(title) in applied or k in applied:
            continue
        # already in master → keep YOUR status, never overwrite/drop
        if k in master:
            continue
        master[k] = {
            'status': 'pending', 'score': int(j.get('score', 0) or 0),
            'title': title, 'company': company or '?',
            'location': str(j.get('location', '') or 'Remote'),
            'rate': str(j.get('rate', '') or ''),
            'c2c': 'yes' if j.get('is_c2c') else '',
            'source': str(j.get('source', '') or ''),
            'url': url, 'added': datetime.now().strftime('%Y-%m-%d'),
        }
        added += 1

    _save_master(master)

    pending = [r for r in master.values() if (r.get('status') or 'pending').strip().lower() == 'pending']
    pending.sort(key=lambda x: int(x.get('score', 0) or 0), reverse=True)
    done = sum(1 for r in master.values() if (r.get('status') or '').strip().lower() == 'applied')

    print(f'📋 Master list: {len(master)} total | {len(pending)} PENDING | {done} applied | +{added} new today')
    print(f'   File: {MASTER}')
    for r in pending[:10]:
        c2c = ' [C2C]' if r.get('c2c') else ''
        print(f"   {int(r.get('score',0)):3d}% | {r['title'][:50]} @ {r['company'][:22]}{c2c}")

    # ── HTML of PENDING only ──
    rows_html = ''
    for i, r in enumerate(pending, 1):
        sc = int(r.get('score', 0) or 0)
        badge = '🔥' if sc >= 50 else '✅' if sc >= 30 else '📋'
        c2c = ' <span style="background:#34a853;color:#fff;padding:1px 5px;border-radius:3px;font-size:10px">C2C</span>' if r.get('c2c') else ''
        rate = f' · <b style="color:#1a73e8">{html.escape(r["rate"])}</b>' if r.get('rate') else ''
        rows_html += f'''<tr style="border-bottom:1px solid #eee">
<td style="padding:10px;color:#999">{i}</td>
<td style="padding:10px;font-size:13px">{badge} <b>{html.escape(r['title'])}</b>{c2c}<br>
<span style="color:#666">{html.escape(r['company'])} · {html.escape(r['location'])}{rate}</span>
<br><span style="color:#aaa;font-size:11px">Match {sc}% · {html.escape(r.get('source',''))} · added {r.get('added','')}</span></td>
<td style="padding:10px;text-align:center"><a href="{html.escape(r['url'])}" target="_blank" rel="noopener" style="background:#1a73e8;color:#fff;padding:9px 16px;border-radius:5px;text-decoration:none;font-size:13px;font-weight:bold">Apply →</a></td></tr>'''

    today = datetime.now().strftime('%A, %B %d %Y')
    urls_js = json.dumps([r['url'] for r in pending])
    html_doc = f'''<!DOCTYPE html><html><body style="font-family:Helvetica,Arial,sans-serif;color:#222;max-width:760px;margin:0 auto">
<div style="background:linear-gradient(135deg,#1a73e8,#34a853);color:#fff;padding:22px;border-radius:8px 8px 0 0">
<h2 style="margin:0">📋 {len(pending)} Jobs to Apply Yourself</h2>
<p style="margin:6px 0 0;opacity:.9">{today} · ranked best-first · {done} already applied · nothing drops off until you apply</p>
</div>
<div style="padding:6px 16px;border:1px solid #ddd;border-top:0">
<p style="font-size:12px;color:#666">These are jobs CI/CD could NOT auto-apply to. Open them in tabs, apply, close each. When you finish the whole list, click "I'm Done" — it marks them all so tomorrow shows ONLY new jobs (no duplicates).</p>
<p style="font-size:12px;background:#fff8e1;border:1px solid #ffe082;padding:8px 12px;border-radius:6px;color:#795548">💡 The <b>Open All / Done buttons work in the browser file</b> (email hides buttons for security). Apply links below work anywhere. Browser file: <code>~/Downloads/CV/job-finder/manual_apply_list.html</code></p>
<div style="text-align:center;margin:14px 0">
<button onclick="openAll()" style="background:#1a73e8;color:#fff;border:0;padding:14px 24px;border-radius:8px;font-size:15px;font-weight:bold;cursor:pointer;margin:4px">🌐 Open All {len(pending)} in Chrome Tabs</button>
<button onclick="openBatch()" style="background:#fbbc04;color:#222;border:0;padding:14px 24px;border-radius:8px;font-size:15px;font-weight:bold;cursor:pointer;margin:4px">📑 Open Next 10 Tabs</button>
<button onclick="cvDone()" style="background:#34a853;color:#fff;border:0;padding:14px 24px;border-radius:8px;font-size:15px;font-weight:bold;cursor:pointer;margin:4px">✓ I'm Done — Mark All Applied</button>
<div id="cvmsg" style="margin-top:10px;font-size:13px;color:#333"></div>
</div>
<script>
var JOB_URLS = {urls_js};
var batchStart = 0;
function openAll() {{
  if (!confirm('Open all ' + JOB_URLS.length + ' jobs in new Chrome tabs? (Allow pop-ups if asked.)')) return;
  JOB_URLS.forEach(function(u, i) {{ setTimeout(function() {{ window.open(u, '_blank'); }}, i * 300); }});
  document.getElementById('cvmsg').innerHTML = '🌐 Opening ' + JOB_URLS.length + ' tabs (staggered). Close each after applying.';
}}
function openBatch() {{
  var end = Math.min(batchStart + 10, JOB_URLS.length);
  for (var i = batchStart; i < end; i++) {{ window.open(JOB_URLS[i], '_blank'); }}
  document.getElementById('cvmsg').innerHTML = '📑 Opened jobs ' + (batchStart+1) + '–' + end + ' of ' + JOB_URLS.length + '. Click again for the next 10.';
  batchStart = end >= JOB_URLS.length ? 0 : end;
}}
function cvDone() {{
  var cmd = 'cds-cv-done';
  try {{ navigator.clipboard.writeText(cmd); }} catch(e) {{}}
  document.getElementById('cvmsg').innerHTML =
    '✅ Command copied. Paste this in your terminal to finish the batch:<br>' +
    '<code style="background:#eee;padding:6px 10px;border-radius:4px;display:inline-block;margin-top:6px;font-size:15px">cds-cv-done</code><br>' +
    '<span style="color:#888">This marks all as applied → tomorrow only NEW jobs appear.</span>';
}}
</script>
<table style="border-collapse:collapse;width:100%">
<tr style="background:#333;color:#fff"><th style="padding:8px;width:30px">#</th><th style="padding:8px;text-align:left">Job</th><th style="padding:8px;width:90px">Action</th></tr>
{rows_html}</table></div>
<div style="padding:10px 16px;background:#f8f9fa;border:1px solid #ddd;border-top:0;border-radius:0 0 8px 8px">
<p style="color:#888;font-size:11px;margin:0">Persistent list — a job stays here until you mark it applied in the CSV. No job is ever missed. Finished? Run <code>cds-cv-done</code>.</p>
</div></body></html>'''

    with open(OUT_HTML, 'w') as f:
        f.write(html_doc)
    print(f'📄 Saved {OUT_HTML}')

    if RESEND_KEY and pending:
        payload = json.dumps({
            'from': RESEND_FROM, 'to': [EMAIL],
            'subject': f'📋 {len(pending)} Jobs to Apply Yourself — {datetime.now().strftime("%b %d")}',
            'html': html_doc,
        })
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(payload); tmp = f.name
        try:
            r = subprocess.run(['curl', '-s', '-X', 'POST', 'https://api.resend.com/emails',
                '-H', f'Authorization: Bearer {RESEND_KEY}', '-H', 'Content-Type: application/json',
                '-d', f'@{tmp}'], capture_output=True, text=True, timeout=30)
            os.unlink(tmp)
            print('📧 Emailed the pending list' if '"id"' in r.stdout else f'⚠️ email: {r.stdout[:80]}')
        except Exception as e:
            print(f'⚠️ email error: {e}')
    else:
        print('(no RESEND_KEY — open manual_apply_list.html / manual_apply_master.csv locally)')


if __name__ == '__main__':
    main()
