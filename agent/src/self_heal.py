"""Self-healing module — learns from failures so the agent never fails the same way twice.

Three learning loops:

1. FIELD ANSWERS:  Unknown form question → ask Gemini → save answer → never ask again
   Storage: data/learned_answers.json (committed to repo daily)
   Why JSON not DB: survives between GitHub Actions runs without cache dependency

2. GREENHOUSE 422: Parse error response → identify missing field → patch and retry
   Common errors: missing required field, blank name, invalid question ID

3. EMAIL BOUNCES: Classify bounce type → retry / find alt email / switch transport
"""
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Optional

import httpx

ANSWERS_FILE = Path(__file__).parent.parent / "data" / "learned_answers.json"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

_PROFILE = """Bob Rikh — Senior Java Backend Developer, 10+ years.
Location: Parker CO | Green Card, no sponsorship needed | Available immediately
Work type: C2C / W2 / 1099 (S-Corp), flexible | Rate: $65-80/hr | Remote preferred
Skills: Java 17, Spring Boot, Kafka, Kubernetes, Docker, AWS, MongoDB, Cassandra, GraphQL"""


# ── Answer cache (learned_answers.json) ──────────────────────────────────────

def _load_answers() -> dict:
    try:
        return json.loads(ANSWERS_FILE.read_text())
    except Exception:
        return {}


def _save_answers(answers: dict):
    ANSWERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ANSWERS_FILE.write_text(json.dumps(answers, indent=2, sort_keys=True))


def _question_key(question: str) -> str:
    """Stable hash for a question so we can look it up regardless of whitespace."""
    normalized = re.sub(r'\s+', ' ', question.strip().lower())
    return hashlib.md5(normalized.encode()).hexdigest()[:16]


# ── 1. FIELD ANSWERS ──────────────────────────────────────────────────────────

def answer_unknown_field(
    question: str,
    field_type: str = "text",
    options: Optional[list[str]] = None,
    gemini_key: str = "",
) -> Optional[str]:
    """Return an answer for an unknown form field.

    Flow:
      1. Check learned_answers.json — if cached, return immediately (no API call)
      2. Ask Gemini — generate the answer
      3. Save to learned_answers.json — never ask again
    """
    key = _question_key(question)
    answers = _load_answers()

    # Cache hit
    if key in answers:
        cached = answers[key]
        if cached.get("answer") and cached["answer"].upper() != "SKIP":
            return cached["answer"]
        return None  # previously determined to skip

    # Cache miss — ask Gemini
    if not gemini_key:
        import os
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        return None

    opts_text = f"\nAvailable options: {options}" if options else ""
    prompt = f"""{_PROFILE}

Job application form field:
- Label: "{question}"
- Field type: {field_type}{opts_text}

What exact value should Bob enter? Rules:
- If yes/no → reply Yes or No only
- If dropdown → reply the EXACT option text (from Available options if provided)
- If free text → reply the exact value to type (short, under 50 chars)
- If it asks for a number (years, salary, etc.) → reply just the number
- If genuinely unknown or irrelevant → reply SKIP
Reply with ONLY the value, no explanation."""

    answer = None
    try:
        resp = httpx.post(
            f"{GEMINI_URL}?key={gemini_key}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=15,
        )
        if resp.status_code == 200:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            # Clean up common Gemini response artifacts
            text = text.strip('"').strip("'").strip()
            answer = text if text.upper() != "SKIP" else None
    except Exception:
        pass

    # Save result (even SKIP — so we don't ask again)
    answers[key] = {
        "question": question,
        "answer": answer or "SKIP",
        "field_type": field_type,
        "options": options,
        "learned_at": time.strftime("%Y-%m-%d"),
        "source": "gemini",
    }
    _save_answers(answers)

    if answer:
        print(f"      🧠 Learned: '{question[:50]}' → '{answer[:30]}'")
    return answer


def bulk_seed_answers(qa_pairs: list[tuple[str, str]]):
    """Pre-load known answers so Gemini is never called for common questions."""
    answers = _load_answers()
    for question, answer in qa_pairs:
        key = _question_key(question)
        if key not in answers:
            answers[key] = {
                "question": question,
                "answer": answer,
                "learned_at": time.strftime("%Y-%m-%d"),
                "source": "seed",
            }
    _save_answers(answers)


# ── 2. GREENHOUSE 422 ADAPTATION ─────────────────────────────────────────────

_422_PATTERNS = [
    # "Missing required field: job_application[resume]"
    (re.compile(r"missing required field.*?job_application\[(\w+)\]", re.I), "missing_field"),
    # "First name can't be blank"
    (re.compile(r"(first.?name|last.?name|email|phone)\s+can.?t be blank", re.I), "blank_field"),
    # "Question N is required" (custom questions by ID)
    (re.compile(r"question\s+(\d+)\s+(is required|can.?t be blank)", re.I), "missing_question"),
    # "Invalid value for question N"
    (re.compile(r"invalid value for question\s+(\d+)", re.I), "invalid_question_value"),
]

_FIELD_DEFAULTS = {
    "first_name": "Bob",
    "last_name": "Rikh",
    "email": "bobrikh75@gmail.com",
    "phone": "3472685917",
    "phone_number": "3472685917",
    "cover_letter_text": (
        "Available immediately. Flexible: W2 / 1099 / C2C (S-Corp). "
        "Rate: $65-80/hr. Green Card holder, no sponsorship needed."
    ),
    "linkedin_profile": "https://www.linkedin.com/in/bobrikh75/",
    "website": "https://www.linkedin.com/in/bobrikh75/",
    "current_company": "",
    "current_title": "Senior Java Backend Developer",
    "location": "Parker, CO",
}


def adapt_greenhouse_422(error_body: str, form_data: dict) -> dict:
    """Parse a Greenhouse 422 error and patch form_data to fix it.

    Returns a copy of form_data with the fix applied.
    If nothing can be fixed automatically, returns form_data unchanged.
    """
    patched = dict(form_data)
    error_lower = error_body.lower()
    fixed = False

    for pattern, error_type in _422_PATTERNS:
        m = pattern.search(error_body)
        if not m:
            continue

        if error_type == "missing_field":
            field = m.group(1).lower()
            key = f"job_application[{field}]"
            if key not in patched and field in _FIELD_DEFAULTS:
                patched[key] = _FIELD_DEFAULTS[field]
                print(f"      🔧 422 fix: added missing field '{field}'")
                fixed = True

        elif error_type == "blank_field":
            field = re.sub(r'[^a-z_]', '', m.group(1).lower().replace(' ', '_').replace('-', '_'))
            key = f"job_application[{field}]"
            if not patched.get(key) and field in _FIELD_DEFAULTS:
                patched[key] = _FIELD_DEFAULTS[field]
                print(f"      🔧 422 fix: filled blank field '{field}'")
                fixed = True

        elif error_type == "missing_question":
            # Can't auto-fill unknown question IDs — log and move on
            q_id = m.group(1)
            print(f"      ⚠️  422: custom question {q_id} required but unknown — cannot auto-fill")

        elif error_type == "invalid_question_value":
            q_id = m.group(1)
            # Remove the invalid answer so the submission doesn't fail on it
            key = f"job_application[question_{q_id}]"
            if key in patched:
                del patched[key]
                print(f"      🔧 422 fix: removed invalid answer for question {q_id}")
                fixed = True

    if not fixed:
        print(f"      ⚠️  422: could not auto-fix — {error_body[:120]}")

    return patched


# ── 3. EMAIL BOUNCE HANDLING ──────────────────────────────────────────────────

# Bounce classification → action
_BOUNCE_ACTIONS = {
    # Permanent — don't retry
    "no such user":           "blacklist",
    "user unknown":           "blacklist",
    "does not exist":         "blacklist",
    "invalid address":        "blacklist",
    "address rejected":       "blacklist",
    "550":                    "blacklist",   # SMTP 550 = mailbox not found
    # Temporary — retry in 3 days
    "mailbox full":           "retry_3d",
    "over quota":             "retry_3d",
    "temporarily unavailable":"retry_3d",
    "452":                    "retry_3d",    # SMTP 452 = insufficient storage
    # Deliverability — switch transport
    "blocked":                "switch_transport",
    "spam":                   "switch_transport",
    "blacklisted":            "switch_transport",
    "policy":                 "switch_transport",
    # Rate limit
    "too many":               "retry_1h",
    "rate limit":             "retry_1h",
}


def classify_bounce(error_message: str) -> tuple[str, str]:
    """Classify a bounce/SMTP error. Returns (action, reason).

    Actions: blacklist | retry_3d | retry_1h | switch_transport | unknown
    """
    lower = error_message.lower()
    for pattern, action in _BOUNCE_ACTIONS.items():
        if pattern in lower:
            return action, pattern
    return "unknown", "unrecognized error"


def handle_email_bounce(
    email: str,
    error_message: str,
    contacted: dict,
    email_hash_fn,
) -> dict:
    """Update contacted dict based on bounce classification.

    Returns the modified contacted entry (caller saves contacted.json).
    """
    action, reason = classify_bounce(error_message)
    key = email_hash_fn(email)

    entry = contacted.get(key, {})
    entry["bounce_action"] = action
    entry["bounce_reason"] = reason
    entry["bounce_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    if action == "blacklist":
        entry["blacklisted"] = True
        print(f"      🚫 Blacklisted {email}: {reason}")
    elif action == "retry_3d":
        from datetime import datetime, timedelta
        retry_at = (datetime.now() + timedelta(days=3)).isoformat()
        entry["retry_after"] = retry_at
        print(f"      🔁 Retry {email} after 3 days ({reason})")
    elif action == "switch_transport":
        entry["force_smtp"] = True  # flag for outreach.py to use SMTP instead of Resend
        print(f"      🔄 Switch transport for {email} ({reason})")
    elif action == "retry_1h":
        from datetime import datetime, timedelta
        entry["retry_after"] = (datetime.now() + timedelta(hours=1)).isoformat()
        print(f"      🔁 Retry {email} in 1h ({reason})")

    contacted[key] = entry
    return entry


# ── Seed known answers on first import ───────────────────────────────────────
# These bypass Gemini entirely — answers are 100% known and never change.
_SEED_QA = [
    ("Are you authorized to work in the United States?", "Yes"),
    ("Are you legally authorized to work in the US?", "Yes"),
    ("Will you now or in the future require visa sponsorship?", "No"),
    ("Do you require sponsorship to work in the United States?", "No"),
    ("Are you willing to undergo a background check?", "Yes"),
    ("Do you consent to a background check?", "Yes"),
    ("When can you start?", "Immediately"),
    ("What is your notice period?", "Immediately"),
    ("Are you willing to relocate?", "No"),
    ("What is your desired salary?", "150000"),
    ("What is your expected hourly rate?", "75"),
    ("What is your compensation expectation?", "75"),
    ("How did you hear about this position?", "Online Job Board"),
    ("Where did you find this job?", "Online Job Board"),
    ("What is your highest level of education?", "Bachelor's Degree"),
    ("What is your gender?", "Decline to self-identify"),
    ("What is your race or ethnicity?", "Decline to self-identify"),
    ("Are you a veteran?", "I am not a protected veteran"),
    ("Do you have a disability?", "I do not wish to answer"),
    ("What is your LinkedIn profile URL?", "https://www.linkedin.com/in/bobrikh75/"),
    ("Are you currently employed?", "Yes"),
    ("What is your current employer?", "Charter Communications"),
    ("What state do you reside in?", "Colorado"),
    ("What country do you live in?", "United States"),
    ("Are you at least 18 years of age?", "Yes"),
    ("Are you able to work remotely?", "Yes"),
    ("Do you have experience with Java?", "Yes"),
    ("Do you have experience with Spring Boot?", "Yes"),
    ("Do you have experience with AWS?", "Yes"),
    ("Do you have experience with Kubernetes?", "Yes"),
    ("Do you have experience with Kafka?", "Yes"),
    ("Do you have experience with microservices?", "Yes"),
    ("Years of experience with Java?", "10"),
    ("Years of professional software development experience?", "10"),
]

# Seed on module load — fast (just writes JSON if not already seeded)
if not ANSWERS_FILE.exists():
    bulk_seed_answers(_SEED_QA)
