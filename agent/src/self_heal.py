"""Deterministic error classifier, retry config, and deep self-healing for job failures.

Healing levels — each level only runs if the previous level was exhausted:
  Level 1 — classify + route: skip / retry_api / use_browser
  Level 2 — learn from failure: patch known form fields, mark company as browser_only
  Level 3 — record unresolvable: save with full diagnostic so human can review

Design rules:
  - No guessing: every fix is deterministic (pattern match or known-safe default)
  - No breaking: each fix is additive, never deletes existing behavior
  - Optional: disable any level via DEEP_HEAL_CONFIG
  - Transparent: every action is logged with WHY

Usage (Level 1):
    from src.self_heal import classify_error, get_retry_config, STRATEGY
    error_type = classify_error(error_msg)
    cfg = get_retry_config(error_type)

Usage (Level 2):
    from src.self_heal import DeepHeal
    healer = DeepHeal(db, companies_file)
    patched = healer.attempt(job_entry, error_type, strategy_tried)
    # patched=True → job was re-queued with a fix applied
    # patched=False → unresolvable, save to failed_jobs.json
"""

import json
import re
import time
from pathlib import Path

# ── Level 1: Error classifier ─────────────────────────────────────────────────

_ERROR_PATTERNS: list[tuple[str, list[str]]] = [
    ("already_applied",  ["already applied", "duplicate application", "previously applied",
                          "already submitted"]),
    ("not_found",        ["404", "not found", "position closed", "job removed",
                          "no longer available", "job has been filled"]),
    ("otp_timeout",      ["otp timeout", "no verification code", "code not received",
                          "email timeout", "verification email"]),
    ("captcha_failed",   ["recaptcha failed", "captcha failed", "challenge failed",
                          "bot detection"]),
    ("network_error",    ["connection error", "connection refused", "ssl error",
                          "network", "dns", "read timeout", "connect timeout"]),
    ("form_field",       ["required field", "field is required", "missing required",
                          "invalid field", "start date", "available cities",
                          "must answer", "answer required"]),
    ("api_400",          ["http 400", "bad request", "http 422", "unprocessable entity",
                          "malformed"]),
    ("remix_context",    ["remixcontext", "cannot fetch job page", "parse error",
                          "cannot fetch"]),
]


def classify_error(error_msg: str) -> str:
    lower = error_msg.lower()
    for error_type, patterns in _ERROR_PATTERNS:
        if any(p in lower for p in patterns):
            return error_type
    return "unknown"


class STRATEGY:
    SKIP        = "skip"
    RETRY_API   = "retry_api"
    RETRY_OTP   = "retry_otp"
    USE_BROWSER = "use_browser"


RETRY_CONFIG: dict[str, dict] = {
    "already_applied": {"strategy": STRATEGY.SKIP,        "max_retries": 0, "delay_s": 0},
    "not_found":       {"strategy": STRATEGY.SKIP,        "max_retries": 0, "delay_s": 0},
    "otp_timeout":     {"strategy": STRATEGY.RETRY_OTP,   "max_retries": 2, "delay_s": 45},
    "captcha_failed":  {"strategy": STRATEGY.RETRY_API,   "max_retries": 2, "delay_s": 8},
    "network_error":   {"strategy": STRATEGY.RETRY_API,   "max_retries": 3, "delay_s": 12},
    "form_field":      {"strategy": STRATEGY.USE_BROWSER, "max_retries": 0, "delay_s": 0},
    "api_400":         {"strategy": STRATEGY.USE_BROWSER, "max_retries": 0, "delay_s": 0},
    "remix_context":   {"strategy": STRATEGY.USE_BROWSER, "max_retries": 0, "delay_s": 0},
    "unknown":         {"strategy": STRATEGY.USE_BROWSER, "max_retries": 0, "delay_s": 0},
}


def get_retry_config(error_type: str) -> dict:
    return RETRY_CONFIG.get(error_type, RETRY_CONFIG["unknown"])


# ── Level 2: Deep self-healing ────────────────────────────────────────────────

# Toggle each healing behavior independently.
# Set to False to disable without touching any other logic.
DEEP_HEAL_CONFIG = {
    # After N API failures for one company → mark it browser_only in companies.json
    # so next run skips the API attempt entirely and goes straight to Playwright.
    "learn_company_api_failures": True,
    "api_fail_threshold": 3,          # how many API fails before marking browser_only

    # When error message names a specific form field → add a known-safe default answer
    # to the DB approved_answers table so Playwright can fill it next run.
    # Only fires for fields in KNOWN_SAFE_ANSWERS below — never guesses.
    "patch_known_form_fields": True,

    # After patching a form field answer → re-queue the job for one more browser attempt.
    # Disable if you want to review patches manually first.
    "requeue_after_patch": True,
}

# Known-safe answers for common Greenhouse custom questions.
# These are factually correct for Bobur — not guesses.
# Add new fields here as you discover them in error logs.
KNOWN_SAFE_ANSWERS: dict[str, str] = {
    "start date":               "Immediately",
    "when can you start":       "Immediately",
    "available start":          "Immediately",
    "available cities":         "Remote",
    "city":                     "Remote",
    "work authorization":       "Green Card",
    "authorized to work":       "Yes",
    "visa sponsorship":         "No",
    "require sponsorship":      "No",
    "salary":                   "Negotiable",
    "compensation":             "Negotiable",
    "expected salary":          "Negotiable",
    "veteran status":           "I am not a veteran",
    "are you a veteran":        "No",
    "disability status":        "I do not have a disability",
    "do you have a disability": "No",
    "willing to relocate":      "No",
    "relocation":               "No",
    "years of experience":      "7",
    "years experience":         "7",
    "gender":                   "Prefer not to say",
    "race":                     "Prefer not to say",
    "ethnicity":                "Prefer not to say",
}


def _extract_field_name(error_msg: str) -> str | None:
    """Pull the field name out of a form_field error message."""
    # Matches: 'required field: "Start date"', "field 'available_cities' missing", etc.
    for pattern in [
        r'required field[:\s]+["\']?([^"\']+)["\']?',
        r'field[:\s]+["\']([^"\']+)["\']',
        r'answer required.*?[:\s]+["\']?([^"\']+)["\']?',
        r'must answer[:\s]+["\']?([^"\']+)["\']?',
    ]:
        m = re.search(pattern, error_msg, re.I)
        if m:
            return m.group(1).strip().lower()
    return None


def _find_safe_answer(field_name: str) -> str | None:
    """Return a known-safe answer for this field, or None if we don't know it."""
    for key, answer in KNOWN_SAFE_ANSWERS.items():
        if key in field_name or field_name in key:
            return answer
    return None


class DeepHeal:
    """Level 2 self-healer. Call attempt() after all Level 1 retries are exhausted.

    Returns True if a fix was applied and the job was re-queued for another attempt.
    Returns False if the error is unresolvable — caller should save to failed_jobs.json.
    """

    def __init__(self, db, companies_file: str, browser_queue: list):
        self._db = db
        self._companies_file = companies_file
        self._browser_queue = browser_queue  # shared ref — appending here re-queues the job

    def attempt(self, job: dict, error_type: str, error_msg: str) -> bool:
        """Try every applicable Level 2 fix. Returns True if job was re-queued."""
        fixed = False

        # Fix A: Mark company as browser_only after repeated API failures
        if (DEEP_HEAL_CONFIG["learn_company_api_failures"]
                and error_type in ("api_400", "remix_context", "unknown")):
            if self._mark_browser_only_if_needed(job["company"]):
                print(f"  🧠 DeepHeal: {job['company']} → marked browser_only "
                      f"(API never works here)")
                # Don't re-queue this job — it will go straight to browser next run

        # Fix B: Patch a missing form field answer
        if DEEP_HEAL_CONFIG["patch_known_form_fields"] and error_type == "form_field":
            field_name = _extract_field_name(error_msg)
            if field_name:
                answer = _find_safe_answer(field_name)
                if answer:
                    patched = self._save_form_answer(field_name, answer, job["company"])
                    if patched:
                        print(f"  🧠 DeepHeal: patched form field '{field_name}' = '{answer}'")
                        if DEEP_HEAL_CONFIG["requeue_after_patch"]:
                            job["strategy_tried"] = "api_browser_patched"
                            job["deep_heal_patch"] = f"{field_name}={answer}"
                            self._browser_queue.append(job)
                            print(f"  🔄 DeepHeal: re-queued {job['title']} with patched answer")
                            fixed = True
                else:
                    # Field is unknown — log it so human can add it to KNOWN_SAFE_ANSWERS
                    print(f"  ⚠️  DeepHeal: unknown field '{field_name}' — "
                          f"add to KNOWN_SAFE_ANSWERS in self_heal.py")

        return fixed

    def _mark_browser_only_if_needed(self, company: str) -> bool:
        """Add company to browser_only list in companies.json if API fails threshold."""
        if not DEEP_HEAL_CONFIG["learn_company_api_failures"]:
            return False
        try:
            path = Path(self._companies_file)
            data = json.loads(path.read_text()) if path.exists() else {}
            browser_only = set(data.get("browser_only", []))
            if company in browser_only:
                return False  # already marked
            # Count API failures for this company in failed_jobs.json
            failed_file = path.parent / "failed_jobs.json"
            if failed_file.exists():
                failed = json.loads(failed_file.read_text()).get("jobs", [])
                api_fails = sum(
                    1 for j in failed
                    if j.get("company") == company
                    and j.get("error_type") in ("api_400", "remix_context", "unknown")
                )
                if api_fails >= DEEP_HEAL_CONFIG["api_fail_threshold"]:
                    browser_only.add(company)
                    data["browser_only"] = sorted(browser_only)
                    path.write_text(json.dumps(data, indent=2))
                    return True
        except Exception as e:
            print(f"  ⚠️  DeepHeal._mark_browser_only_if_needed: {e}")
        return False

    def _save_form_answer(self, field_name: str, answer: str, company: str) -> bool:
        """Persist a form field answer to the DB approved_answers table."""
        try:
            self._db.execute(
                """CREATE TABLE IF NOT EXISTS approved_answers
                   (field_name TEXT, answer TEXT, company TEXT, created_at TEXT,
                    PRIMARY KEY (field_name, company))""")
            self._db.execute(
                """INSERT OR REPLACE INTO approved_answers
                   (field_name, answer, company, created_at)
                   VALUES (?, ?, ?, ?)""",
                (field_name, answer, company, time.strftime('%Y-%m-%dT%H:%M:%S')))
            self._db.commit()
            return True
        except Exception as e:
            print(f"  ⚠️  DeepHeal._save_form_answer: {e}")
            return False
