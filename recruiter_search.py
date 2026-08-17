#!/usr/bin/env python3
"""
Recruiter search pipeline.
Reads companies from found_jobs.json → Hunter.io → Apollo.io → Snov.io → Tomba.io → outreach.
Cascade: Hunter (domain) → Apollo (company + Tomba LinkedIn enrichment) → Snov → Tomba domain.
"""
import json, os, re, urllib.request, urllib.parse
from typing import Optional

HUNTER_KEY = os.environ.get('HUNTER_API_KEY', '')
APOLLO_KEY = os.environ.get('APOLLO_API_KEY', '')
SNOV_USER_ID = os.environ.get('SNOV_USER_ID', '')
SNOV_SECRET = os.environ.get('SNOV_API_SECRET', '')
TOMBA_KEY = os.environ.get('TOMBA_KEY', '')
TOMBA_SECRET = os.environ.get('TOMBA_SECRET', '')

_RECRUITER_KEYWORDS = {
    'recruiter', 'talent', 'staffing', 'sourcer', 'headhunter',
    'hiring manager', 'human resources', 'hr manager', 'hr director',
    'talent acquisition', 'people operations',
}

_KNOWN_DOMAINS = {
    'collabera': 'collabera.com',
    'teksystems': 'teksystems.com',
    'tek systems': 'teksystems.com',
    'pyramid consulting': 'pyramidci.com',
    'mastech': 'mastechdigital.com',
    'mastech digital': 'mastechdigital.com',
    'skiltrek': 'skiltrek.com',
    'amerit consulting': 'ameritconsulting.com',
    'kforce': 'kforce.com',
    'robert half': 'roberthalf.com',
    'genesis10': 'genesis10.com',
    'motion recruitment': 'motionrecruitment.com',
    'cynet systems': 'cynetsystems.com',
}

MAX_COMPANIES = 20
MAX_EMAILS_PER_RUN = 15


def _is_recruiter(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in _RECRUITER_KEYWORDS)


def _company_to_domain(company: str) -> Optional[str]:
    lower = company.lower().strip()
    for k, v in _KNOWN_DOMAINS.items():
        if k in lower:
            return v
    clean = re.sub(r'[^a-z0-9]', '', lower)
    return f'{clean}.com' if clean else None


def _get_json(url: str, extra_headers: dict = None) -> dict:
    headers = {'User-Agent': 'Mozilla/5.0'}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f'  ⚠️  GET failed: {e}')
        return {}


def _post_json(url: str, payload: dict, extra_headers: dict = None) -> dict:
    data = json.dumps(payload).encode()
    headers = {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f'  ⚠️  POST failed: {e}')
        return {}


def hunter_search(domain: str) -> list[dict]:
    if not HUNTER_KEY:
        return []
    url = (f'https://api.hunter.io/v2/domain-search'
           f'?domain={urllib.parse.quote(domain)}&department=hr&limit=10&api_key={HUNTER_KEY}')
    data = _get_json(url)
    results = []
    for p in data.get('data', {}).get('emails', []):
        title = p.get('position', '')
        email = p.get('value', '')
        if not email or not _is_recruiter(title):
            continue
        results.append({
            'email': email,
            'name': f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
            'title': title,
            'source': 'hunter',
            'confidence': p.get('confidence', 0),
        })
    return results


def apollo_search(company: str) -> list[dict]:
    if not APOLLO_KEY:
        return []
    payload = {
        'api_key': APOLLO_KEY,
        'q_organization_name': company,
        'person_titles': ['recruiter', 'talent acquisition', 'HR manager', 'staffing manager'],
        'per_page': 10,
    }
    data = _post_json(
        'https://api.apollo.io/v1/mixed_people/search',
        payload,
        extra_headers={'Cache-Control': 'no-cache', 'X-Api-Key': APOLLO_KEY},
    )
    results = []
    for p in data.get('people', []):
        email = p.get('email', '')
        linkedin_url = p.get('linkedin_url', '')
        source = 'apollo'
        # Apollo sometimes redacts email — enrich via Tomba LinkedIn lookup
        if (not email or 'placeholder' in email) and linkedin_url:
            email = tomba_linkedin_lookup(linkedin_url) or ''
            if email:
                source = 'apollo+tomba'
        if not email:
            continue
        results.append({
            'email': email,
            'name': p.get('name', ''),
            'title': p.get('title', ''),
            'linkedin_url': linkedin_url,
            'source': source,
            'confidence': 85,
        })
    return results


def _snov_token() -> str:
    if not SNOV_USER_ID or not SNOV_SECRET:
        return ''
    data = urllib.parse.urlencode({
        'grant_type': 'client_credentials',
        'client_id': SNOV_USER_ID,
        'client_secret': SNOV_SECRET,
    }).encode()
    req = urllib.request.Request(
        'https://api.snov.io/v1/oauth/access_token',
        data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()).get('access_token', '')
    except Exception:
        return ''


def snov_search(domain: str) -> list[dict]:
    if not SNOV_USER_ID:
        return []
    token = _snov_token()
    if not token:
        return []
    data = _post_json(
        'https://api.snov.io/v2/domain-emails-with-info',
        {'domain': domain, 'type': 'all', 'limit': 10},
        extra_headers={'Authorization': f'Bearer {token}'},
    )
    results = []
    for p in data.get('emails', []):
        title = p.get('position', '')
        email = p.get('email', '')
        if not email or not _is_recruiter(title):
            continue
        results.append({
            'email': email,
            'name': f"{p.get('firstName', '')} {p.get('lastName', '')}".strip(),
            'title': title,
            'source': 'snov',
            'confidence': 80,
        })
    return results


def tomba_domain_search(domain: str) -> list[dict]:
    """Tomba.io domain search — 50 free/month, alternative to Hunter."""
    if not TOMBA_KEY:
        return []
    headers = {'X-Tomba-Key': TOMBA_KEY, 'X-Tomba-Secret': TOMBA_SECRET}
    data = _get_json(
        f'https://api.tomba.io/v1/domain-search/{urllib.parse.quote(domain)}',
        extra_headers=headers,
    )
    results = []
    for p in data.get('data', {}).get('emails', []):
        title = p.get('position', '')
        email = p.get('email', '')
        if not email or not _is_recruiter(title):
            continue
        results.append({
            'email': email,
            'name': f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
            'title': title,
            'source': 'tomba',
            'confidence': p.get('score', 0),
        })
    return results


def tomba_linkedin_lookup(linkedin_url: str) -> Optional[str]:
    """Tomba.io LinkedIn profile → verified email. Used to enrich Apollo results."""
    if not TOMBA_KEY or not linkedin_url:
        return None
    headers = {'X-Tomba-Key': TOMBA_KEY, 'X-Tomba-Secret': TOMBA_SECRET}
    url = f'https://api.tomba.io/v1/linkedin?url={urllib.parse.quote(linkedin_url)}'
    data = _get_json(url, extra_headers=headers)
    return data.get('data', {}).get('email') or None


def find_recruiters_for_company(company: str) -> list[dict]:
    """Hunter → Apollo (Tomba enriches missing emails) → Snov → Tomba domain."""
    domain = _company_to_domain(company)
    seen: set[str] = set()
    all_results: list[dict] = []

    def _add(results: list[dict]) -> None:
        for r in results:
            if r['email'] not in seen:
                r['company'] = company
                r['domain'] = domain or ''
                all_results.append(r)
                seen.add(r['email'])

    if domain:
        _add(hunter_search(domain))
    if not all_results:
        _add(apollo_search(company))  # calls tomba_linkedin_lookup internally
    if not all_results and domain:
        _add(snov_search(domain))
    if not all_results and domain:
        _add(tomba_domain_search(domain))

    return all_results


def load_companies() -> list[str]:
    if not os.path.exists('found_jobs.json'):
        return []
    try:
        with open('found_jobs.json') as f:
            data = json.load(f)
        jobs = data if isinstance(data, list) else data.get('jobs', [])
        companies = list({j.get('company', '').strip() for j in jobs if j.get('company', '').strip()})
        return [c for c in companies if len(c) > 2][:MAX_COMPANIES]
    except Exception:
        return []


def main() -> None:
    companies = load_companies()
    if not companies:
        print('⏭️  No companies in found_jobs.json — skipping recruiter search')
        return

    print(f'🔍 Searching recruiters for {len(companies)} companies...')
    all_recruiters: list[dict] = []

    for company in companies:
        print(f'  → {company}')
        found = find_recruiters_for_company(company)
        if found:
            print(f'    ✅ {len(found)} recruiter(s) via {found[0]["source"]}')
        all_recruiters.extend(found)

    print(f'\n📋 Total found: {len(all_recruiters)} recruiters')

    with open('found_recruiters.json', 'w') as f:
        json.dump(all_recruiters, f, indent=2)

    if not all_recruiters:
        return

    import outreach
    from datetime import datetime

    contacted = outreach.load_contacted()
    sent = 0

    for rec in all_recruiters:
        if sent >= MAX_EMAILS_PER_RUN:
            print(f'⏸️  Daily limit reached ({MAX_EMAILS_PER_RUN})')
            break

        email = rec['email']
        eh = outreach.email_hash(email)
        if eh in contacted:
            continue

        company = rec['company']
        name = rec.get('name', '')
        subject, html = outreach.build_outreach_email(
            name, 'Java Developer / C2C opportunities', company
        )
        print(f'  📧 {name} <{email}> @ {company} ({rec["source"]})...')

        if outreach.send_outreach(email, subject, html):
            now = datetime.now().isoformat()
            contacted[eh] = {
                'email': email,
                'date': now,
                'last_contact': now,
                'job': 'Java Developer C2C',
                'company': company,
                'recruiter': name,
                'title': rec.get('title', ''),
                'source': rec['source'],
                'url': '',
                'replied': False,
                'bounced': False,
                're_engage_count': 0,
            }
            sent += 1
            print(f'  ✅ Sent! ({sent}/{MAX_EMAILS_PER_RUN})')

    outreach.save_contacted(contacted)
    print(f'\n📊 Recruiter outreach: {sent} sent')


if __name__ == '__main__':
    main()
