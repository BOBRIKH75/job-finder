"""AI fallback — when the agent gets stuck, asks free Gemini API to analyze the page."""
import json, os, re
import httpx

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

PROFILE_SUMMARY = """Candidate: Bob Rikh, Senior Java Backend Developer, 10+ years.
Email: bobrikh75@gmail.com | Phone: 347-268-5917 | Location: Parker, CO 80314
Skills: Java 17, Spring Boot, Kafka, Kubernetes, Docker, AWS, MongoDB, Cassandra, GraphQL, REST APIs
Work type: C2C (Corp-to-Corp) contractor | Rate: $55-90/hr | Green Card holder, no sponsorship needed.
LinkedIn: https://www.linkedin.com/in/bobrikh75/
Available immediately. Will not relocate (remote preferred)."""


def ask_ai_about_field(label: str, field_type: str, options: list[str] = None) -> str | None:
    """Ask Gemini: what should I put in this field?"""
    if not GEMINI_KEY:
        return None

    opts = f"\nAvailable options: {options}" if options else ""
    prompt = f"""{PROFILE_SUMMARY}

Job application form field:
- Label: "{label}"
- Type: {field_type}{opts}

What value should Bob fill in? Reply with ONLY the value, nothing else. 
If it's a yes/no question, reply Yes or No.
If it's a dropdown, reply with the exact option text to select.
If you don't know, reply SKIP."""

    try:
        resp = httpx.post(
            f"{GEMINI_URL}?key={GEMINI_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=15,
        )
        if resp.status_code == 200:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            if text.upper() == "SKIP":
                return None
            return text
    except Exception:
        pass
    return None


def ask_ai_about_page(page_text: str, unfilled_fields: list[dict]) -> dict:
    """Ask Gemini to analyze the full page and suggest values for unfilled fields."""
    if not GEMINI_KEY or not unfilled_fields:
        return {}

    fields_desc = "\n".join(
        f"- Field: label='{f.get('label','')}' name='{f.get('name','')}' type='{f.get('type','')}' "
        f"placeholder='{f.get('placeholder','')}' selector='{f.get('selector','')}'"
        for f in unfilled_fields[:10]
    )

    prompt = f"""{PROFILE_SUMMARY}

I'm filling a job application form but got stuck on these fields:
{fields_desc}

Page context (first 1500 chars):
{page_text[:1500]}

For each field, tell me what value Bob should enter.
Reply as JSON: {{"selector": "value", ...}}
Only include fields you're confident about. Use exact selector strings as keys."""

    try:
        resp = httpx.post(
            f"{GEMINI_URL}?key={GEMINI_KEY}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            },
            timeout=20,
        )
        if resp.status_code == 200:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            return json.loads(text)
    except Exception:
        pass
    return {}


def ask_ai_cover_letter(job_title: str, company: str, job_description: str) -> str:
    """Ask Gemini to write a short cover letter for this specific job."""
    if not GEMINI_KEY:
        return (f"Senior Java Backend Developer with 10+ years of experience in Spring Boot, "
                f"Kafka, Kubernetes, and AWS. Green Card holder, available immediately for C2C contract.")

    prompt = f"""{PROFILE_SUMMARY}

Write a 3-sentence cover letter for this job:
Role: {job_title} at {company}
Description: {job_description[:500]}

Be specific to this role. No generic filler. Professional tone. Under 100 words."""

    try:
        resp = httpx.post(
            f"{GEMINI_URL}?key={GEMINI_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        pass
    return (f"I am a Senior Java Backend Developer with 10+ years of experience. "
            f"My skills in Spring Boot, Kafka, and Kubernetes align well with the {job_title} role at {company}. "
            f"I am available immediately for C2C contract work.")
