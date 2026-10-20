#!/usr/bin/env python3
"""
Real end-to-end Greenhouse OTP flow test — headless=True (same as CI).

Applies to ONE live Greenhouse job, walks through the full pipeline:
  form fill → submit → OTP email → code entry → confirmation check

Run: cd agent && python3 test_greenhouse_live.py
"""
import json
import os
import sys
import time
from pathlib import Path

# ── env check — try .env / secrets file if vars not already exported ────────
def _load_secrets():
    """Try common local secrets locations before failing."""
    import shlex
    for candidate in [
        Path(__file__).parent / ".env",
        Path(__file__).parent.parent / ".env",
        Path.home() / ".job-agent-secrets",
        Path.home() / ".config" / "job-agent" / "secrets",
    ]:
        if candidate.exists():
            print(f"  Loading secrets from {candidate}")
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip().strip("export").strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
            return

_load_secrets()

missing = [k for k in ("GMAIL_USER", "GMAIL_APP_PASSWORD") if not os.environ.get(k)]
if missing:
    print(f"❌ Missing env vars: {missing}")
    print()
    print("  Option 1 — create agent/.env:")
    print("    GMAIL_USER=bobrikh75@gmail.com")
    print("    GMAIL_APP_PASSWORD=your-16-char-app-password")
    print()
    print("  Option 2 — export in this shell then rerun:")
    print("    export GMAIL_USER=bobrikh75@gmail.com GMAIL_APP_PASSWORD=xxxx")
    sys.exit(1)

# ── target job ─────────────────────────────────────────────────────────────
# Figure AI — confirmed to trigger OTP flow locally; now testing headless=True
TEST_JOB = {
    "url":     "https://job-boards.greenhouse.io/figureai/jobs/4674754006",
    "title":   "AI Training Infrastructure Engineer",
    "company": "Figure AI",
    "ats_type": "greenhouse",
    "can_automate": True,
    "match_score": 60,
    "is_staffing_firm": False,
}

print("\n" + "="*60)
print("Greenhouse OTP Live Test  (headless=True)")
print("="*60)
print(f"Job:     {TEST_JOB['title']}")
print(f"Company: {TEST_JOB['company']}")
print(f"URL:     {TEST_JOB['url']}")
print(f"Gmail:   {os.environ['GMAIL_USER']}")
print("="*60 + "\n")

# ── launch headless Playwright (exactly as CI does) ─────────────────────────
from playwright.sync_api import sync_playwright

pw  = sync_playwright().start()
browser = pw.chromium.launch(headless=True)          # ← CI mode
context = browser.new_context(
    user_agent=(
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    viewport={"width": 1920, "height": 1080},
)
page = context.new_page()

# ── load profile & learned data ─────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from src.applier   import load_profile, load_learned, apply_to_job, snap, SCREENSHOTS
from src.memory    import get_db, init_db

profile = load_profile()
learned = load_learned()
db      = get_db();  init_db(db)

SCREENSHOTS.mkdir(parents=True, exist_ok=True)
print(f"Screenshots → {SCREENSHOTS}\n")

# ── STEP 1: Test _extract_code with a mock body ─────────────────────────────
print("── Step 1: _extract_code sanity check ──────────────────────────")
from src.email_code_reader import _extract_code
for body, label in [
    ("Your security code is: EEtMwNKJ — expires in 24h",  "all-alpha Greenhouse OTP"),
    ("Code: A1B2C3",                                        "standard alphanumeric"),
    ("verification code 823741 expires",                    "6-digit numeric"),
    ("Security is important. Click here.",                  "false-positive guard"),
]:
    result = _extract_code(body)
    status = "✅" if (result if label != "false-positive guard" else result is None) else "❌"
    print(f"  {status} {label!r:35s}  → {result!r}")
print()

# ── STEP 2: Full apply_to_job with headless=True ─────────────────────────────
print("── Step 2: Full apply flow (headless=True) ──────────────────────")
t0 = time.monotonic()

result = apply_to_job(
    page    = page,
    profile = profile,
    job     = TEST_JOB,
    learned = learned,
    dry_run = False,   # real submission
    db      = db,
    site_needs_cf_solve = False,
)

elapsed = int(time.monotonic() - t0)

print()
print("── Result ───────────────────────────────────────────────────────")
print(f"  Status:        {result.get('status')}")
print(f"  Fields filled: {result.get('fields_filled', 0)}")
print(f"  Elapsed:       {elapsed}s")
for i, att in enumerate(result.get("attempts", []), 1):
    print(f"  Attempt {i}: filled={att.get('filled',0)}  error={att.get('error','—')}")
print()

# ── STEP 3: Check Gmail for confirmation email ───────────────────────────────
print("── Step 3: Check Gmail for 'thank you' confirmation ─────────────")
import imaplib, email as emaillib
from datetime import datetime

try:
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"])
    mail.select('"[Gmail]/All Mail"')
    today = datetime.now().strftime("%d-%b-%Y")
    status, msgs = mail.search(None, f'(SINCE {today} FROM "greenhouse")')
    found = []
    if status == "OK" and msgs[0]:
        for mid in reversed(msgs[0].split()):
            _, data = mail.fetch(mid, "(RFC822)")
            msg = emaillib.message_from_bytes(data[0][1])
            subj = msg.get("Subject", "")
            frm  = msg.get("From", "")
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
            found.append({"subject": subj, "from": frm, "has_thanks": "thank you" in body.lower()})
    mail.logout()
    if found:
        for e in found:
            tag = "✅ CONFIRMATION" if e["has_thanks"] else "📧 email"
            print(f"  {tag}: {e['subject']!r}  from={e['from'][:50]!r}")
    else:
        print("  No Greenhouse emails today yet")
except Exception as ex:
    print(f"  Gmail check failed: {ex}")

print()
print("── Screenshots ──────────────────────────────────────────────────")
snaps = sorted(SCREENSHOTS.glob("*.png"))[-6:]
for s in snaps:
    print(f"  {s.name}")

# ── cleanup ─────────────────────────────────────────────────────────────────
context.close()
pw.stop()

print()
if result.get("status") == "submitted":
    print("✅ SUCCESS — application submitted, check bobrikh75@gmail.com for confirmation")
elif result.get("status") == "email_verification_failed":
    print("❌ OTP step failed — code not obtained or not accepted")
elif result.get("status") == "failed_all_retries":
    print("❌ All retries exhausted — see screenshots and errors above")
else:
    print(f"⚠️  Status: {result.get('status')} — see above for details")
