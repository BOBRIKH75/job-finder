"""Resolve LinkedIn job URLs to actual company career pages.

LinkedIn job pages contain an "Apply" button that redirects to the real company
career page. This script fetches that redirect URL so the agent can auto-apply
directly on the company's ATS (Lever, Greenhouse, Workday, etc.) instead of
being blocked by LinkedIn's bot detection.

Usage:
    python resolve_urls.py              # resolves found_jobs.json in place
    python resolve_urls.py --dry-run    # shows what would change without writing
"""
import json, os, re, sys, time, random, ssl, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

JOBS_FILE = "found_jobs.json"
MAX_RESOLVE = 50  # max LinkedIn URLs to resolve per run (rate limit friendly)
TIMEOUT = 10


def resolve_linkedin_url(url: str) -> str:
    """Follow LinkedIn job URL redirects to find the actual apply page.
    
    Strategy (in order):
    1. Use LinkedIn's PUBLIC jobs-guest endpoint (no login needed, returns HTML)
    2. Fall back to authenticated page with cookies
    3. Follow HTTP redirects
    """
    if "linkedin.com" not in url:
        return url
    
    # Extract job ID from LinkedIn URL
    match = re.search(r'/view/(\d+)', url)
    if not match:
        match = re.search(r'currentJobId=(\d+)', url)
    if not match:
        match = re.search(r'/jobs/(\d+)', url)
    if not match:
        return url
    
    job_id = match.group(1)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    # === METHOD 1: Public jobs-guest endpoint (NO LOGIN, returns HTML with apply link) ===
    # This is the same endpoint search engines use to index LinkedIn jobs
    guest_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    try:
        req = urllib.request.Request(guest_url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx)
        html = resp.read().decode('utf-8', errors='ignore')
        
        # The guest endpoint returns HTML with apply links in known patterns
        patterns = [
            r'href="(https?://[^"]*(?:lever\.co|greenhouse\.io|myworkdayjobs\.com|ashbyhq\.com|bamboohr\.com|jobvite\.com|smartrecruiters\.com|icims\.com)[^"]*)"',
            r'applyUrl["\s:]+["](https?://[^"]+)["]',
            r'companyApplyUrl["\s:]+["](https?://[^"]+)["]',
            r'data-apply-url="(https?://[^"]+)"',
            r'class="apply-button[^"]*"[^>]*href="(https?://[^"]+)"',
            r'href="(https?://[^"]*(?:/jobs/|/careers/|/apply|/position)[^"]*)"',
        ]
        
        for pattern in patterns:
            m = re.search(pattern, html)
            if m:
                found_url = m.group(1).replace("\\u0026", "&").replace("\\/", "/")
                if "linkedin.com" not in found_url:
                    return found_url
    except Exception:
        pass
    
    # === METHOD 2: Authenticated page with cookies (if guest endpoint didn't work) ===
    apply_url = f"https://www.linkedin.com/jobs/view/{job_id}/"
    
    # Add LinkedIn cookies if available
    linkedin_cookies = os.environ.get("LINKEDIN_COOKIES", "")
    if linkedin_cookies:
        try:
            cookie_data = json.loads(linkedin_cookies)
            if isinstance(cookie_data, list):
                cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookie_data if c.get('name'))
                headers["Cookie"] = cookie_str
            elif isinstance(cookie_data, str):
                headers["Cookie"] = cookie_data
        except (json.JSONDecodeError, TypeError):
            if "=" in linkedin_cookies:
                headers["Cookie"] = linkedin_cookies
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    try:
        req = urllib.request.Request(apply_url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx)
        html = resp.read().decode('utf-8', errors='ignore')
        
        # Look for external apply URL in the page
        patterns = [
            r'"applyUrl":"(https?://[^"]+)"',
            r'"companyApplyUrl":"(https?://[^"]+)"',
            r'"applyMethod":\{[^}]*"companyApplyUrl":"(https?://[^"]+)"',
            r'data-apply-url="(https?://[^"]+)"',
            r'"externalApplyLink":"(https?://[^"]+)"',
            r'href="(https?://[^"]*(?:lever|greenhouse|workday|ashby|bamboo|careers|jobs|apply)[^"]*)"',
        ]
        
        for pattern in patterns:
            m = re.search(pattern, html)
            if m:
                found_url = m.group(1).replace("\\u0026", "&").replace("\\/", "/")
                # Skip LinkedIn internal URLs
                if "linkedin.com" not in found_url:
                    return found_url
        
    except Exception:
        pass
    
    # Fallback: try fetching without redirect handler (follow all redirects)
    try:
        req = urllib.request.Request(apply_url, headers=headers)
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            
            # Search for external apply links
            for pattern in [
                r'"applyUrl":"(https?://[^"]+)"',
                r'"companyApplyUrl":"(https?://[^"]+)"',
                r'class="apply-button[^"]*"[^>]*href="(https?://[^"]+)"',
                r'<a[^>]*href="(https?://(?:jobs\.lever\.co|boards\.greenhouse\.io|[^"]*\.myworkdayjobs\.com|[^"]*ashbyhq\.com|[^"]*bamboohr\.com)[^"]*)"',
            ]:
                m = re.search(pattern, html)
                if m:
                    found_url = m.group(1).replace("\\u0026", "&").replace("\\/", "/")
                    if "linkedin.com" not in found_url:
                        return found_url
    except Exception:
        pass
    
    return url  # couldn't resolve, keep original


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Handler that captures redirects instead of following them."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # don't follow


def resolve_jobs(dry_run=False):
    """Resolve LinkedIn URLs in found_jobs.json to actual apply pages."""
    if not os.path.exists(JOBS_FILE):
        print("❌ No found_jobs.json found")
        return
    
    with open(JOBS_FILE) as f:
        data = json.load(f)
    
    jobs = data.get("jobs", [])
    linkedin_jobs = [j for j in jobs if "linkedin.com" in j.get("url", "")]
    other_jobs = [j for j in jobs if "linkedin.com" not in j.get("url", "")]
    
    print(f"📋 {len(jobs)} total jobs | {len(linkedin_jobs)} LinkedIn | {len(other_jobs)} direct")
    
    if not linkedin_jobs:
        print("✅ No LinkedIn URLs to resolve")
        return
    
    # Only resolve top-scored LinkedIn jobs (up to MAX_RESOLVE)
    linkedin_jobs.sort(key=lambda j: j.get("score", 0), reverse=True)
    to_resolve = linkedin_jobs[:MAX_RESOLVE]
    skipped = linkedin_jobs[MAX_RESOLVE:]
    
    print(f"🔍 Resolving {len(to_resolve)} LinkedIn URLs (top scored)...")
    
    resolved_count = 0
    failed_count = 0
    
    # Use thread pool for parallel resolution (5 threads, rate-limited)
    def resolve_with_delay(job):
        time.sleep(random.uniform(0.5, 1.5))  # rate limit
        original = job["url"]
        resolved = resolve_linkedin_url(original)
        return job, original, resolved
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(resolve_with_delay, j) for j in to_resolve]
        for future in as_completed(futures):
            try:
                job, original, resolved = future.result()
                if resolved != original:
                    resolved_count += 1
                    if not dry_run:
                        job["url"] = resolved
                        job["linkedin_url"] = original  # keep original for reference
                    print(f"  ✅ {job.get('company', '?')}: {resolved[:60]}")
                else:
                    failed_count += 1
            except Exception as e:
                failed_count += 1
    
    print(f"\n📊 Resolved: {resolved_count} | Unchanged: {failed_count} | Skipped: {len(skipped)}")
    
    if not dry_run and resolved_count > 0:
        # Rebuild jobs list
        all_jobs = other_jobs + to_resolve + skipped
        data["jobs"] = all_jobs
        data["resolved_count"] = resolved_count
        with open(JOBS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        print(f"💾 Updated found_jobs.json ({resolved_count} URLs resolved)")
    
    # Summary for the agent
    automatable = [j for j in (other_jobs + to_resolve) if "linkedin.com" not in j.get("url", "")]
    print(f"\n🤖 Agent can now try: {len(automatable)} jobs (was {len(other_jobs)} before resolving)")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    resolve_jobs(dry_run=dry_run)
