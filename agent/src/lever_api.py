#!/usr/bin/env python3
"""Lever direct API submitter — bypasses browser/Playwright entirely.

Lever has a free public API for posting applications:
  POST https://api.lever.co/v0/postings/{company}/{posting_id}?key={api_key}

This requires NO authentication from the applicant side.
The company's Lever posting key is embedded in the public job page.

Strategy:
1. GET the Lever job page → extract posting ID from URL
2. POST multipart/form-data to the apply endpoint
3. Detect success via 200 response with "ok" or redirect to thanks page

Lever jobs: jobs.lever.co/{company}/{posting_id}
Apply URL:  api.lever.co/v0/postings/{company}/{posting_id}?key={api_key}

The API key is optional for most Lever boards — many accept submissions without it.
"""

import json
import re
import time
import random
from pathlib import Path
from typing import Optional

import requests

PROFILE_PATH = Path(__file__).parent.parent / "config" / "profile.json"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
}


def load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text())


def _extract_posting_key(html: str) -> Optional[str]:
    """Extract the Lever API key from the job page HTML."""
    # Lever embeds the key in various places
    patterns = [
        r'"apiKey"\s*:\s*"([^"]+)"',
        r'postingApiKey\s*=\s*"([^"]+)"',
        r'data-api-key="([^"]+)"',
        r'/postings/[^?]+\?key=([^"&]+)',
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def _parse_lever_url(url: str) -> Optional[tuple]:
    """Parse a Lever URL into (company, posting_id)."""
    # jobs.lever.co/{company}/{posting_id}
    m = re.search(r'(?:jobs\.)?lever\.co/([^/]+)/([a-f0-9-]+)', url)
    if m:
        return m.group(1), m.group(2)
    return None


def submit_lever_api(
    job_url: str,
    profile: dict,
    resume_path: str,
    dry_run: bool = False,
) -> dict:
    """
    Submit a Lever application via direct multipart POST.

    Returns dict with keys:
      submitted (bool), method (str), error (str, optional)
    """
    parsed = _parse_lever_url(job_url)
    if not parsed:
        return {"submitted": False, "error": "Cannot parse Lever URL"}

    company, posting_id = parsed

    # Extract API key from URL query params first (portal scanner embeds it)
    from urllib.parse import urlparse, parse_qs
    url_params = parse_qs(urlparse(job_url).query)
    api_key = url_params.get("key", [None])[0]

    # Step 1: GET the job page to extract API key (if not already in URL)
    if not api_key:
        try:
            page_resp = requests.get(
                f"https://jobs.lever.co/{company}/{posting_id}",
                headers=_HEADERS,
                timeout=15,
            )
            if page_resp.status_code == 200:
                api_key = _extract_posting_key(page_resp.text)
                # Also check if job is still open
                if "this position is no longer available" in page_resp.text.lower():
                    return {"submitted": False, "error": "Job closed"}
        except Exception:
            pass

    if not api_key:
        return {"submitted": False, "error": "No API key found (Lever requires key for submission)"}

    # Build apply URL
    apply_url = f"https://api.lever.co/v0/postings/{company}/{posting_id}"
    if api_key:
        apply_url += f"?key={api_key}"

    if dry_run:
        print(f"    [DRY RUN LEVER-API] Would POST to {apply_url}")
        return {"submitted": True, "method": "lever_api_dry_run"}

    # Step 2: Build form data
    c2c_note = (
        "Available immediately for C2C / Corp-to-Corp contract. "
        "Green Card holder — no sponsorship needed. "
        f"Rate: ${profile.get('rate_min', 55)}-${profile.get('rate_max', 90)}/hr. "
        "100% remote preferred. Parker, CO."
    )

    form_data = {
        "name": f"{profile['first_name']} {profile['last_name']}",
        "email": profile["email"],
        "phone": profile.get("phone", ""),
        "org": profile.get("current_company", "Charter Communications"),
        "urls[LinkedIn]": profile.get("linkedin", ""),
        "urls[GitHub]": profile.get("github", ""),
        "urls[Portfolio]": profile.get("portfolio", ""),
        "comments": c2c_note,
        # Common custom fields
        "cards[Work Authorization]": "Authorized (Green Card)",
        "cards[Sponsorship]": "No — Green Card holder",
    }

    resume_file = Path(resume_path).expanduser()
    if not resume_file.exists():
        return {"submitted": False, "error": f"Resume not found: {resume_path}"}

    # Step 3: Submit
    post_headers = {
        **_HEADERS,
        "Origin": "https://jobs.lever.co",
        "Referer": f"https://jobs.lever.co/{company}/{posting_id}",
    }

    try:
        time.sleep(random.uniform(1.5, 3.0))

        with open(resume_file, "rb") as fh:
            files = {"resume": (resume_file.name, fh, "application/pdf")}
            resp = requests.post(
                apply_url,
                data=form_data,
                files=files,
                headers=post_headers,
                timeout=30,
                allow_redirects=True,
            )

        # Success detection
        if resp.status_code == 200:
            try:
                body = resp.json()
                if body.get("ok") or body.get("applicationId"):
                    return {"submitted": True, "method": "lever_api"}
            except Exception:
                pass
            # Some Lever boards return HTML success page
            if any(w in resp.text.lower() for w in
                   ["thank you", "application received", "submitted", "we've received"]):
                return {"submitted": True, "method": "lever_api"}

        if resp.status_code == 201:
            return {"submitted": True, "method": "lever_api"}

        if resp.status_code == 303:
            # Redirect to thank-you page = success
            location = resp.headers.get("Location", "")
            if "thanks" in location or "thank" in location or "confirmation" in location:
                return {"submitted": True, "method": "lever_api"}

        if resp.status_code == 400:
            try:
                err = resp.json()
                return {"submitted": False, "error": f"400: {err.get('message', resp.text[:200])}"}
            except Exception:
                return {"submitted": False, "error": f"400: {resp.text[:200]}"}

        return {"submitted": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

    except Exception as exc:
        return {"submitted": False, "error": str(exc)}


def is_lever_url(url: str) -> bool:
    """Check if URL is a Lever job posting."""
    return "lever.co/" in url.lower()
