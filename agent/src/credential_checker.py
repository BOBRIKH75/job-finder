"""Credential checker — validates all secrets at agent startup.

Called once per run, before any platform work starts.
Returns: dict of {name: status} and a set of DISABLED platforms.

Rules:
  - Missing or invalid → disable that platform, send ONE alert email, continue with others
  - Never crash the pipeline over a single bad credential
  - Only alert if the status CHANGED from last run (no spam)
"""
import base64
import json
import os
import smtplib
import time
from pathlib import Path

import httpx

# ── Platform → credentials they need ─────────────────────────────────────────
PLATFORM_DEPS: dict[str, list[str]] = {
    "email_reports":   ["RESEND_KEY"],
    "gmail_smtp":      ["GMAIL_USER", "GMAIL_APP_PASSWORD"],
    "ai_features":     ["GEMINI_API_KEY"],
    "linkedin":        ["LINKEDIN_COOKIES"],
    "indeed":          ["INDEED_COOKIES"],
}

# State file so we only alert on NEW failures (not every run)
_STATE_FILE = Path(__file__).parent.parent / "data" / "credential_state.json"


def _load_prev_state() -> dict:
    try:
        return json.loads(_STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict):
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Individual checks ─────────────────────────────────────────────────────────

def _check_resend(key: str) -> str:
    """Validate Resend key format (re_xxxxx) — can't test without sending."""
    if not key:
        return "missing"
    if not key.startswith("re_") or len(key) < 10:
        return "invalid_format"
    return "ok"


def _check_gemini(key: str) -> str:
    """Test Gemini key by listing models (free, read-only call)."""
    if not key:
        return "missing"
    try:
        resp = httpx.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
            timeout=10,
        )
        if resp.status_code == 200:
            return "ok"
        if resp.status_code in (400, 403):
            return "invalid_key"
        return f"http_{resp.status_code}"
    except Exception as e:
        return f"network_error: {str(e)[:40]}"


def _check_linkedin_cookies(encoded: str) -> str:
    """Decode LINKEDIN_COOKIES and verify li_at is present."""
    if not encoded:
        return "missing"
    try:
        cookies = json.loads(base64.b64decode(encoded).decode())
        has_li_at = any(c.get("name") == "li_at" for c in cookies if isinstance(c, dict))
        if not has_li_at:
            return "missing_li_at"
        # li_at cookies expire ~1 year — check if value looks fresh (non-empty)
        li_at_val = next((c["value"] for c in cookies if c.get("name") == "li_at"), "")
        if len(li_at_val) < 20:
            return "li_at_looks_empty"
        return "ok"
    except (base64.binascii.Error, json.JSONDecodeError):
        return "decode_error"


def _check_gmail(user: str, password: str) -> str:
    """Test Gmail App Password via SMTP (closes immediately, no email sent)."""
    if not password:
        return "missing"
    if not user:
        return "missing_gmail_user"
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=12) as s:
            s.starttls()
            s.login(user, password)
        return "ok"
    except smtplib.SMTPAuthenticationError:
        return "auth_failed"
    except Exception as e:
        return f"network_error: {str(e)[:40]}"


def _check_indeed_cookies(encoded: str) -> str:
    """Verify INDEED_COOKIES base64 decodes to a list."""
    if not encoded:
        return "missing"
    try:
        cookies = json.loads(base64.b64decode(encoded).decode())
        if not isinstance(cookies, list) or len(cookies) == 0:
            return "empty_or_invalid"
        return "ok"
    except Exception:
        return "decode_error"


# ── Main check ────────────────────────────────────────────────────────────────

def check_all() -> tuple[dict, set[str]]:
    """Run all credential checks.

    Returns:
        results  — {credential_name: status_string}
        disabled — set of platform names that should be skipped this run
    """
    env = os.environ

    results = {
        "RESEND_KEY":          _check_resend(env.get("RESEND_KEY", "")),
        "GEMINI_API_KEY":      _check_gemini(env.get("GEMINI_API_KEY", "")),
        "LINKEDIN_COOKIES":    _check_linkedin_cookies(env.get("LINKEDIN_COOKIES", "")),
        "GMAIL_APP_PASSWORD":  _check_gmail(env.get("GMAIL_USER", ""), env.get("GMAIL_APP_PASSWORD", "")),
        "INDEED_COOKIES":      _check_indeed_cookies(env.get("INDEED_COOKIES", "")),
    }

    # Determine which platforms to disable
    disabled: set[str] = set()
    for platform, deps in PLATFORM_DEPS.items():
        for dep in deps:
            if results.get(dep, "ok") != "ok":
                disabled.add(platform)
                break

    return results, disabled


def report_and_alert(results: dict, disabled: set[str]) -> None:
    """Print status table. Send ONE alert email for NEW failures only."""
    print("\n  🔑 Credential check:")
    for name, status in results.items():
        icon = "✅" if status == "ok" else ("⏭️" if status == "missing" else "❌")
        print(f"     {icon} {name}: {status}")

    if disabled:
        print(f"  ⚠️  Disabled platforms: {', '.join(sorted(disabled))}")

    # Find credentials that NEWLY failed (weren't failing last run)
    prev = _load_prev_state()
    new_failures = {
        name: status
        for name, status in results.items()
        if status != "ok" and prev.get(name) == "ok"
    }

    _save_state(results)

    if not new_failures:
        return  # no new failures → no alert needed

    _send_alert(new_failures, disabled)


def _send_alert(failures: dict, disabled: set[str]):
    """Send a single Resend email listing all newly-failed credentials."""
    resend_key = os.environ.get("RESEND_KEY", "")
    gmail_user = os.environ.get("GMAIL_USER", "bobrikh75@gmail.com")

    lines = [f"  • {name}: {status}" for name, status in failures.items()]
    body = (
        "Job Agent — Credential Alert\n\n"
        "The following credentials stopped working since the last run:\n\n"
        + "\n".join(lines)
        + f"\n\nDisabled platforms this run: {', '.join(sorted(disabled)) or 'none'}\n"
        "All other platforms are running normally.\n\n"
        "Action needed:\n"
    )

    if "LINKEDIN_COOKIES" in failures:
        body += "  → Re-extract LinkedIn cookies: run extract_li_cookies.py locally\n"
    if "GEMINI_API_KEY" in failures:
        body += "  → Check/rotate your Google AI Studio key\n"
    if "GMAIL_APP_PASSWORD" in failures:
        body += "  → Generate a new Gmail App Password at myaccount.google.com\n"
    if "RESEND_KEY" in failures:
        body += "  → Check your Resend.com dashboard for the API key\n"

    subject = f"⚠️ Job Agent — Credential Expired: {', '.join(failures.keys())}"

    sent = False
    if resend_key:
        import urllib.request
        payload = json.dumps({
            "from": "Job Agent <onboarding@resend.dev>",
            "to": [gmail_user],
            "subject": subject,
            "text": body,
        }).encode()
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=payload,
            headers={
                "Authorization": f"Bearer {resend_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=15)
            sent = True
            print(f"  📧 Credential alert sent to {gmail_user}")
        except Exception as e:
            print(f"  ⚠️  Could not send alert email: {e}")

    if not sent:
        # Fallback: print loudly so it shows in GitHub Actions log
        print("\n" + "=" * 60)
        print("CREDENTIAL ALERT (email send failed — see log):")
        print(body)
        print("=" * 60 + "\n")
