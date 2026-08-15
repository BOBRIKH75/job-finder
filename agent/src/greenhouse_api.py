#!/usr/bin/env python3
"""Greenhouse direct API submitter — bypasses browser/Playwright entirely.

Strategy:
1. GET job-boards.greenhouse.io/{company}/jobs/{id} → parse __remixContext JSON
2. Extract question definitions from jobPost.questions
3. Build multipart/form-data with auto-answers keyed from profile
4. POST to submitPath (boards.greenhouse.io/{company}/jobs/{id})
5. Detect success via redirect to confirmationPath or confirmation text
"""

import re
import json
import time
import random
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

import requests

PROFILE_PATH = Path(__file__).parent.parent / "config" / "profile.json"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text())


def _extract_remix_context(html: str) -> Optional[dict]:
    m = re.search(r"window\.__remixContext = (\{)", html)
    if not m:
        return None
    txt = html[m.start(1):]
    depth, end = 0, 0
    for i, c in enumerate(txt):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    try:
        return json.loads(txt[:end])
    except Exception:
        return None


def _get_job_data(company: str, job_id: str) -> Optional[dict]:
    """GET the Greenhouse job page and extract question definitions + submitPath."""
    url = f"https://job-boards.greenhouse.io/{company}/jobs/{job_id}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        ctx = _extract_remix_context(resp.text)
        if not ctx:
            return None
        loader = ctx.get("state", {}).get("loaderData", {})
        return loader.get("routes/$url_token_.jobs_.$job_post_id")
    except Exception:
        return None


def _answer_question(question: dict, profile: dict) -> Optional[str]:
    """Return the best answer for one question field as a string."""
    label = question.get("label", "").lower().strip()
    fields = question.get("fields", [])
    if not fields:
        return None

    field = fields[0]
    fname = field.get("name", "")
    ftype = field.get("type", "")

    # Standard identity fields handled by the main loop
    if fname in ("first_name", "last_name", "email", "phone",
                 "resume", "resume_text", "cover_letter", "cover_letter_text"):
        return None

    if ftype == "input_text":
        if "linkedin" in label:
            return profile.get("linkedin", "")
        if "github" in label:
            return profile.get("github", "")
        if "preferred name" in label:
            return profile.get("first_name", "")
        if "current company" in label or "employer" in label:
            return "Charter Communications"
        if "salary" in label or "rate" in label or "compensation" in label:
            return str(profile.get("rate_target", 75))
        return ""

    if ftype == "textarea":
        return ""

    if ftype in ("multi_value_single_select", "multi_value_multi_select"):
        values = field.get("values", [])
        if not values:
            return None

        def _pick(keyword: str) -> Optional[str]:
            for v in values:
                if keyword in str(v.get("label", "")).lower():
                    return str(v["value"])
            return None

        # Sponsorship / visa → No
        if any(k in label for k in ("sponsor", "visa", "immigration", "work authorization")):
            ans = _pick("no") or _pick("false")
            if ans:
                return ans
            for v in values:
                if v["value"] == 0:
                    return "0"

        # Pronouns → He/him
        if "pronoun" in label:
            return _pick("he/him") or str(values[0]["value"])

        # State / province → Colorado
        if any(k in label for k in ("state", "province", "reside")):
            return _pick("colorado") or str(values[0]["value"])

        # Previously employed → have not
        if "previously" in label and "employed" in label:
            return _pick("have not") or _pick("never") or str(values[0]["value"])

        # How did you hear → LinkedIn
        if any(k in label for k in ("hear", "learn about", "source", "referr")):
            return _pick("linkedin") or _pick("other") or str(values[0]["value"])

        # Generic Yes/No: default No (safe conservative answer)
        if len(values) == 2:
            lbls = [str(v.get("label", "")).lower() for v in values]
            if "yes" in lbls and "no" in lbls:
                return _pick("no")

        # Optional: prefer "decline" / "prefer not to say"
        if not question.get("required", True):
            ans = _pick("prefer not") or _pick("decline")
            if ans:
                return ans

        return str(values[0]["value"])

    return None


def submit_greenhouse_api(
    job_url: str,
    profile: dict,
    resume_path: str,
    dry_run: bool = False,
) -> dict:
    """
    Submit a Greenhouse application via direct multipart POST.

    Returns dict with keys:
      submitted (bool), method (str), error (str, optional)
    """
    m = re.search(r"greenhouse\.io/([^/?#]+)/jobs/(\d+)", job_url)
    if not m:
        return {"submitted": False, "error": "Cannot parse greenhouse URL"}

    company, job_id = m.group(1), m.group(2)

    # Extract ?token= from URL — some jobs require it in the POST body
    _qs = parse_qs(urlparse(job_url).query)
    url_token = _qs.get("token", [None])[0]

    route_data = _get_job_data(company, job_id)
    if not route_data:
        return {"submitted": False, "error": "Cannot fetch job page / parse remixContext"}

    submit_url = route_data.get(
        "submitPath", f"https://boards.greenhouse.io/{company}/jobs/{job_id}"
    )
    confirmation_path = route_data.get("confirmationPath", "/confirmation")
    job_post = route_data.get("jobPost", {})
    questions = job_post.get("questions", [])

    if dry_run:
        print(f"    [DRY RUN GH-API] Would POST to {submit_url} ({len(questions)} questions)")
        return {"submitted": True, "method": "direct_api_dry_run"}

    # Build form data
    form_data = {
        "job_application[first_name]": profile["first_name"],
        "job_application[last_name]": profile["last_name"],
        "job_application[email]": profile["email"],
        "job_application[phone]": profile.get("phone", ""),
    }
    if url_token:
        form_data["job_application[token]"] = url_token

    for q in questions:
        for field in q.get("fields", []):
            fname = field.get("name", "")
            if fname in ("first_name", "last_name", "email", "phone",
                         "resume", "resume_text", "cover_letter", "cover_letter_text"):
                continue
            answer = _answer_question(q, profile)
            if answer is not None and answer != "":
                form_data[f"job_application[{fname}]"] = answer

    resume_file = Path(resume_path).expanduser()
    if not resume_file.exists():
        return {"submitted": False, "error": f"Resume not found: {resume_path}"}

    post_headers = {
        **_HEADERS,
        "Accept": "application/json, text/html, */*",
        "Referer": f"https://job-boards.greenhouse.io/{company}/jobs/{job_id}",
        "Origin": "https://job-boards.greenhouse.io",
    }

    try:
        time.sleep(random.uniform(2, 4))

        with open(resume_file, "rb") as fh:
            files = {"job_application[resume]": (resume_file.name, fh, "application/pdf")}
            resp = requests.post(
                submit_url,
                data=form_data,
                files=files,
                headers=post_headers,
                timeout=30,
                allow_redirects=True,
            )

        # Success detection
        conf_slug = confirmation_path.rstrip("/").split("/")[-1]
        if conf_slug and conf_slug in (resp.url or ""):
            return {"submitted": True, "method": "direct_api"}

        if resp.status_code in (200, 201):
            text_lower = resp.text.lower()
            if any(w in text_lower for w in
                   ["thank you", "application received", "confirmation", "successfully submitted"]):
                return {"submitted": True, "method": "direct_api"}

        if resp.status_code == 302:
            location = resp.headers.get("Location", "")
            if "confirmation" in location or "thank" in location:
                return {"submitted": True, "method": "direct_api"}

        if resp.status_code == 422:
            try:
                err = resp.json()
                return {"submitted": False, "error": f"422: {err.get('message', resp.text[:300])}"}
            except Exception:
                return {"submitted": False, "error": f"422: {resp.text[:300]}"}

        return {"submitted": False, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}

    except Exception as exc:
        return {"submitted": False, "error": str(exc)}


def is_greenhouse_url(url: str) -> bool:
    return "greenhouse.io" in url.lower()
