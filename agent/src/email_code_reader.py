#!/usr/bin/env python3
"""Read verification codes from Gmail for Greenhouse/ATS applications.

When a site (Greenhouse, etc.) requires email verification:
1. Waits for the email to arrive (polls IMAP every 3 sec, max 30 sec)
2. Extracts the verification code from the email body
3. Returns it so the agent can enter it on the page

Requires: GMAIL_USER + GMAIL_APP_PASSWORD environment variables.
"""
import imaplib
import email
import os
import re
import time
from datetime import datetime, timedelta
from typing import Optional


# Module-level set to track codes we've already used this session.
# This prevents reusing the same code even if IMAP returns the same email.
_USED_CODES: set = set()


def get_verification_code(
    sender_filter: str = "greenhouse",
    max_wait_seconds: int = 30,
    poll_interval: int = 3,
    company: str = "",
) -> Optional[str]:
    """Poll Gmail IMAP for a FRESH verification code email.
    
    CRITICAL: Each Greenhouse application sends a UNIQUE code. Reusing an old
    code silently fails (page redirects but application is NOT actually submitted).
    
    VERIFIED LIVE (2026-09-01): the code email ALWAYS has the subject
    "Security code for your application to <Company>" (sender is Greenhouse even
    for Airbnb/Affirm/etc). The old FROM-only search grabbed the newest
    greenhouse email, which is usually a "Thank you for applying" CONFIRMATION
    (no code) → parser returned None or a junk token → wrong code entered.
    Fix: search by SUBJECT "security code" first, and if we know the company,
    prefer the email whose subject names that company.
    
    Args:
        sender_filter: keyword to match in sender address (fallback only)
        max_wait_seconds: how long to wait for the email to arrive
        poll_interval: seconds between IMAP checks
        company: the employer name for the current application (best-match filter)
    
    Returns:
        The verification code as a string, or None if not found
    """
    gmail_user = os.environ.get("GMAIL_USER", "")
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD", "")
    
    if not gmail_user or not gmail_pass:
        print("      ⚠️ Email verifier: GMAIL_USER or GMAIL_APP_PASSWORD not set")
        return None
    
    print(f"      📧 Waiting for verification email (max {max_wait_seconds}s)...")
    if _USED_CODES:
        print(f"      📧 Already used codes this session: {_USED_CODES}")
    
    # NOTE: We do NOT mark old emails as SEEN anymore.
    # That was KILLING fresh codes — the code arrives within 5-10s of Submit,
    # and marking-all-seen was destroying it before we could read it.
    # Instead we rely on _USED_CODES set to skip already-used codes.
    # Wait for Greenhouse to send the new code (5-20s typical).
    #
    # FRESHNESS CUTOFF: capture the time this OTP wait began. A legitimate code
    # email arrives within seconds of clicking submit. We reject any email whose
    # Date header is older than (cutoff - 5 min buffer) so a stale code from a
    # PREVIOUS run/session (e.g. cb164f12) can never be reused across processes —
    # _USED_CODES only dedups within one process, this guards across processes.
    from email.utils import parsedate_to_datetime
    from datetime import timezone
    _freshness_cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    time.sleep(12)
    
    start_time = time.time()
    while time.time() - start_time < max_wait_seconds:
        try:
            # Connect to Gmail IMAP
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(gmail_user, gmail_pass)
            mail.select('"[Gmail]/All Mail"')  # Search ALL mail, not just Primary tab
            
            # Search for RECENT emails (today only)
            # (datetime/timedelta come from the module-level import — do NOT
            # re-import locally or the freshness-cutoff use above becomes UnboundLocal)
            today = datetime.now().strftime("%d-%b-%Y")
            # PRIMARY: subject-based — the code email is ALWAYS titled
            # "Security code for your application to <Company>". This reliably
            # excludes "Thank you for applying" confirmation emails.
            if sender_filter == "__subject__":
                search_criteria = f'(SINCE {today} SUBJECT "security code")'
            elif sender_filter:
                search_criteria = f'(SINCE {today} FROM "{sender_filter}")'
            else:
                search_criteria = f'(SINCE {today})'
            status, messages = mail.search(None, search_criteria)
            
            if status == "OK" and messages[0]:
                msg_ids = messages[0].split()
                # Process from NEWEST to OLDEST
                for msg_id in reversed(msg_ids):
                    status, msg_data = mail.fetch(msg_id, "(RFC822)")
                    if status != "OK":
                        continue
                    
                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    # COMPANY MATCH: when we know the employer, skip code emails
                    # whose subject is for a DIFFERENT company. The subject is
                    # "Security code for your application to <Company>". This
                    # stops us entering Airbnb's code on an Affirm application.
                    if company:
                        subj = str(msg.get("Subject", "")).lower()
                        comp = company.lower().strip()
                        # only enforce when this looks like a security-code email
                        if 'security code' in subj and comp and comp[:12] not in subj:
                            mail.store(msg_id, '+FLAGS', '\\Seen')
                            continue

                    # FRESHNESS GUARD: reject emails that arrived before this OTP
                    # attempt began (minus a 5-min buffer). A real Greenhouse code
                    # arrives seconds after submit; an older email is a stale code
                    # from a previous run/session and would be rejected by the ATS.
                    try:
                        _msg_date = parsedate_to_datetime(msg.get("Date", ""))
                        if _msg_date is not None:
                            if _msg_date.tzinfo is None:
                                _msg_date = _msg_date.replace(tzinfo=timezone.utc)
                            if _msg_date < _freshness_cutoff:
                                mail.store(msg_id, '+FLAGS', '\\Seen')
                                continue  # stale email — skip, keep waiting for fresh
                    except Exception:
                        pass  # unparseable date — fall through and try the code

                    # Extract body text — prefer text/plain; fall back to text/html
                    plain_body = ""
                    html_body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain" and not plain_body:
                                plain_body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                            elif part.get_content_type() == "text/html" and not html_body:
                                html_body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    else:
                        raw = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                        if "<html" in raw.lower() or "<div" in raw.lower():
                            html_body = raw
                        else:
                            plain_body = raw

                    # Greenhouse sends HTML-only emails — strip tags so regex hits real code,
                    # not CSS color values like #15372C which match the digit+letter pattern.
                    if plain_body:
                        body = plain_body
                    elif html_body:
                        body = re.sub(r'<[^>]+>', ' ', html_body)
                        body = re.sub(r'\s+', ' ', body).strip()
                    else:
                        body = ""

                    # Extract verification code
                    code = _extract_code(body)
                    
                    # ALWAYS mark as SEEN — whether we use the code or not
                    mail.store(msg_id, '+FLAGS', '\\Seen')
                    
                    if code:
                        if code in _USED_CODES:
                            print(f"      ⏭️  Skipping already-used code: {code}")
                            continue
                        # FRESH code found!
                        print(f"      ✅ Got FRESH verification code: {code}")
                        _USED_CODES.add(code)
                        mail.logout()
                        return code
            
            mail.logout()
        except Exception as e:
            print(f"      ⚠️ Email check error: {str(e)[:60]}")
        
        time.sleep(poll_interval)
    
    print(f"      ❌ No FRESH verification email received within {max_wait_seconds}s (used codes: {_USED_CODES})")
    return None


def _extract_code(body: str) -> Optional[str]:
    """Extract verification code from email body.

    Greenhouse (and most ATS) codes are ALPHANUMERIC, 6-8 chars, e.g. 15372C,
    EEtMwNKJ, 4SSHR6aH, cb164f12. The previous digit-only patterns truncated
    mixed codes (15372C -> 15372) which Greenhouse then rejected. This version
    matches the FULL token and anchors on the surrounding context word so it
    never grabs a CSS colour (#15372C) or a stray 4-digit fragment.
    """
    # A code token: 4-8 alphanumerics, not glued to other word chars.
    _CODE = r'([A-Za-z0-9]{4,8})'

    def _valid(candidate: str) -> bool:
        """Reject obvious non-codes (pure short words, all-lowercase words)."""
        if not candidate:
            return False
        has_digit = any(c.isdigit() for c in candidate)
        has_letter = any(c.isalpha() for c in candidate)
        # Pure digits: accept only 4-8 length (OTP numeric codes)
        if has_digit and not has_letter:
            return 4 <= len(candidate) <= 8
        # Mixed digit+letter: always a code (15372C, 4SSHR6aH, cb164f12)
        if has_digit and has_letter:
            return True
        # All letters: only accept a RANDOM-looking Greenhouse 8-char token.
        # Real codes (EEtMwNKJ, XWHfrfdC, OhbuBMBU) have >=3 uppercase scattered
        # irregularly. CamelCase words (LinkedIn, YourName, JobAlert) have exactly
        # 1-2 uppercase at word boundaries — require >=3 uppercase to exclude them.
        if has_letter and not has_digit and len(candidate) == 8:
            return (sum(1 for c in candidate if c.isupper()) >= 3
                    and sum(1 for c in candidate if c.islower()) >= 1)
        return False

    # PASS 1 — context-anchored: the code that follows a verification keyword.
    # This is the highest-confidence match and wins over anything elsewhere.
    context_patterns = [
        r'(?:verification|security|confirm(?:ation)?)\s*(?:code|number|pin|token)?\s*(?:is)?\s*[:\-]?\s*' + _CODE,
        r'(?:code|pin|otp)\s*(?:is)?\s*[:\-]?\s*' + _CODE,
        r'(?:paste|enter|use)\s*(?:this)?\s*(?:code)?\s*[:\-]?\s*' + _CODE,
        r'<(?:strong|b)>\s*' + _CODE + r'\s*</(?:strong|b)>',
    ]
    for pattern in context_patterns:
        for m in re.finditer(pattern, body, re.IGNORECASE):
            candidate = m.group(1)
            if _valid(candidate):
                return candidate

    # PASS 2 — standalone token fallback (no context word nearby).
    # Skip anything immediately preceded by '#' (CSS colour like #15372C).
    for m in re.finditer(r'(?<![A-Za-z0-9])' + _CODE + r'(?![A-Za-z0-9])', body):
        start = m.start(1)
        if start > 0 and body[start - 1] == '#':
            continue  # CSS colour, not a code
        candidate = m.group(1)
        has_digit = any(c.isdigit() for c in candidate)
        has_letter = any(c.isalpha() for c in candidate)
        # digit+letter mix (15372C), OR a standalone 6-8 digit OTP (291847),
        # OR the 8-char Greenhouse alpha token (EEtMwNKJ).
        if has_digit and has_letter and _valid(candidate):
            return candidate
        if has_digit and not has_letter and 6 <= len(candidate) <= 8:
            return candidate
        if has_letter and not has_digit and len(candidate) == 8 and _valid(candidate):
            return candidate

    return None


def enter_verification_code(page, code: str) -> bool:
    """Enter the verification code on the page and submit.
    
    Greenhouse security code page uses OTP-style multi-box inputs:
    8 separate input boxes (#security-input-0 through #security-input-7).
    The correct approach is to CLICK the first box and TYPE the full code —
    the component auto-distributes characters across boxes.
    
    Fallback: single text input for other ATS systems.
    """
    try:
        # ═══════════════════════════════════════════════════════════════════
        # Strategy 0: OTP-STYLE MULTI-BOX INPUT (Greenhouse pattern)
        # Greenhouse uses #security-input-0 through #security-input-7
        # Must click first box then TYPE (not fill) — component auto-advances
        # ═══════════════════════════════════════════════════════════════════
        otp_first_selectors = [
            '#security-input-0',
            'input[id^="security-input"]',
            'input[id^="otp-input"]',
            'input[id^="code-input"]',
            'input[id^="verification-input"]',
        ]
        for otp_sel in otp_first_selectors:
            try:
                first_box = page.locator(otp_sel).first
                if first_box.is_visible(timeout=500):
                    # Click the first box to focus it
                    first_box.click()
                    page.wait_for_timeout(300)
                    # TYPE the full code — the OTP component auto-distributes
                    page.keyboard.type(code, delay=100)
                    print(f"      ✅ Typed code into OTP boxes starting at: {otp_sel}")
                    page.wait_for_timeout(500)
                    _click_submit_after_code(page)
                    return True
            except Exception:
                continue

        # Also detect OTP by checking if there are multiple 1-char inputs in sequence
        try:
            single_char_inputs = page.locator('input[maxlength="1"]:visible')
            count = single_char_inputs.count()
            if count >= 6:  # OTP = 6-8 single-char boxes
                print(f"      🔑 Detected {count} single-char inputs (OTP pattern)")
                single_char_inputs.first.click()
                page.wait_for_timeout(300)
                page.keyboard.type(code, delay=100)
                print(f"      ✅ Typed code into {count} OTP boxes")
                page.wait_for_timeout(500)
                _click_submit_after_code(page)
                return True
        except Exception:
            pass

        # ═══════════════════════════════════════════════════════════════════
        # Strategy 1: SINGLE text input (Lever, Ashby, Workday, etc.)
        # ═══════════════════════════════════════════════════════════════════
        selectors = [
            # Greenhouse-specific patterns
            'input[name="security_code"]',
            'input[name*="security_code"]',
            'input[name*="security-code"]',
            'input[name="job_application[security_code]"]',
            'input[id*="security_code"]',
            'input[id*="security-code"]',
            'input[aria-label*="security code" i]',
            'input[aria-label*="verification code" i]',
            'input[placeholder*="security code" i]',
            'input[placeholder*="Enter code" i]',
            'input[placeholder*="enter the code" i]',
            'input[placeholder*="paste" i]',
            # Generic code input patterns
            'input[name*="code"]',
            'input[name*="verification"]',
            'input[name*="otp"]',
            'input[name*="pin"]',
            'input[name*="token"]',
            'input[placeholder*="code" i]',
            'input[placeholder*="verification" i]',
            'input[autocomplete="one-time-code"]',
            'input[type="text"][maxlength="6"]',
            'input[type="text"][maxlength="7"]',
            'input[type="text"][maxlength="8"]',
            'input[type="number"]',
            '#verification_code',
            '#security_code',
            '#code',
        ]
        
        for sel in selectors:
            try:
                field = page.locator(sel).first
                if field.is_visible(timeout=500):
                    field.fill(code)
                    print(f"      ✅ Entered code in: {sel}")
                    _click_submit_after_code(page)
                    return True
            except Exception:
                continue
        
        # Strategy 2: Find input by associated label text containing "code" or "security"
        try:
            labels = page.locator('label')
            for i in range(labels.count()):
                try:
                    label = labels.nth(i)
                    label_text = label.inner_text(timeout=1000).strip().lower()
                    if any(kw in label_text for kw in ['security code', 'verification code', 'enter code', 'enter the code', 'paste.*code']):
                        label_for = label.get_attribute('for')
                        if label_for:
                            field = page.locator(f'#{label_for}')
                            if field.count() > 0 and field.first.is_visible():
                                # Check if this is an OTP box (maxlength=1 or id ends in -0/-1)
                                maxlen = field.first.get_attribute('maxlength') or ''
                                if maxlen == '1' or label_for.endswith('-0') or label_for.endswith('-1'):
                                    # OTP box — click and TYPE
                                    field.first.click()
                                    page.wait_for_timeout(300)
                                    page.keyboard.type(code, delay=100)
                                    print(f"      ✅ Typed code via label (OTP): '{label_text[:40]}' → #{label_for}")
                                else:
                                    field.first.fill(code)
                                    print(f"      ✅ Entered code via label: '{label_text[:40]}' → #{label_for}")
                                _click_submit_after_code(page)
                                return True
                except Exception:
                    continue
        except Exception:
            pass
        
        # Strategy 3: FALLBACK — find ANY visible text input on the page that's empty
        # On Greenhouse security code page, there's typically only ONE input field
        try:
            all_inputs = page.locator('input[type="text"]:visible, input:not([type]):visible')
            for i in range(all_inputs.count()):
                try:
                    inp = all_inputs.nth(i)
                    input_type = inp.get_attribute('type') or 'text'
                    if input_type in ('text', ''):
                        current_val = inp.input_value()
                        if not current_val:  # Empty field — likely the code input
                            inp.fill(code)
                            print(f"      ✅ Entered code in fallback empty text input #{i}")
                            _click_submit_after_code(page)
                            return True
                except Exception:
                    continue
        except Exception:
            pass
        
        print("      ⚠️ Could not find verification code input field")
        # Debug: log what inputs ARE on the page
        try:
            all_visible = page.locator('input:visible')
            count = all_visible.count()
            print(f"      🔍 Debug: {count} visible inputs on page")
            for i in range(min(count, 5)):
                inp = all_visible.nth(i)
                name = inp.get_attribute('name') or ''
                itype = inp.get_attribute('type') or ''
                iid = inp.get_attribute('id') or ''
                print(f"         #{i}: name='{name}' type='{itype}' id='{iid}'")
        except Exception:
            pass
        return False
    except Exception as e:
        print(f"      ⚠️ Error entering code: {str(e)[:60]}")
        return False


def _click_submit_after_code(page) -> None:
    """After entering verification code, click the submit/verify button.
    
    Greenhouse security code page uses 'Resubmit your application' or similar.
    Also try pressing Enter as fallback (many forms submit on Enter).
    """
    page.wait_for_timeout(1000)  # Give page time to register the code input
    
    # Try button selectors — ordered from most specific (Greenhouse) to generic
    for btn_sel in [
        # Greenhouse specific — their actual button texts (case-insensitive via :has-text)
        'button:has-text("Resubmit your application")',
        'button:has-text("resubmit your application")',
        'button:has-text("Resubmit")',
        'button:has-text("Submit application")',
        'button:has-text("Submit Application")',
        # Generic
        'button:has-text("Submit")',
        'button:has-text("Verify")',
        'button:has-text("Confirm")',
        'button:has-text("Continue")',
        'input[type="submit"]',
        'button[type="submit"]',
        # Greenhouse specific selectors
        'input[value="Submit Application"]',
        'input[value="Resubmit your application"]',
        'button[data-testid*="submit"]',
        # Any button that's the only one on the page (security code page is simple)
        'form button',
    ]:
        try:
            btn = page.locator(btn_sel).first
            if btn.is_visible(timeout=1000):
                btn.click()
                print(f"      ✅ Clicked submit after code: {btn_sel}")
                # Wait for page to START navigating away from the OTP form.
                # Greenhouse typically redirects within 2-5s; headless CI needs up to 8s.
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=8000)
                except Exception:
                    page.wait_for_timeout(4000)
                return
        except Exception:
            continue
    
    # FALLBACK: Press Enter — many forms submit the code on Enter keypress
    try:
        print("      ⏎ No button found — pressing Enter to submit code...")
        page.keyboard.press("Enter")
        try:
            page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            page.wait_for_timeout(4000)
        return
    except Exception:
        pass
    
    print("      ⚠️ No submit button found AND Enter didn't work — code was entered but NOT submitted")


def handle_email_verification(page, skip_detection: bool = False, company: str = "") -> bool:
    """Detect and handle email verification challenge on current page.
    
    Call this when the page shows a verification/security code prompt.
    Returns True if verification was successful.
    
    Args:
        page: Playwright page object
        skip_detection: If True, skip the page text signal check (caller already confirmed
                       this is a verification page, e.g. submit_and_verify returned 
                       email_verification_required). Goes straight to reading code from Gmail.
        company: employer name for the current application (matches the right code email)
    """
    if not skip_detection:
        # Check if page is asking for email verification
        try:
            page_text = page.locator("body").inner_text(timeout=3000).lower()
        except Exception:
            return False
        
        verification_signals = [
            "verification code",
            "security code",
            "sent a code",
            "check your email",
            "verify your email",
            "enter the code",
            "confirmation code",
            "enter code",
            "email a code",
            "sent you a code",
            "verify your identity",
            "one-time code",
            "one time code",
            "6-digit code",
            "digit code",
            "copy and paste this code",
            "resubmit your application",
        ]
        
        if not any(signal in page_text for signal in verification_signals):
            return False
    
    print("      📧 Email verification detected — reading code from Gmail...")
    
    # Try multiple ATS senders dynamically (Greenhouse, Lever, Ashby, Workday, generic)
    # In CI (ubuntu-hosted Linux), OTP email delivery from cloud IPs takes longer.
    # Self-hosted Mac runner (residential IP) gets emails in ~20s; CI can take 2+ minutes.
    _ci_mode = (os.environ.get('GITHUB_ACTIONS') == 'true'
                and os.environ.get('RUNNER_OS', '').lower() == 'linux')
    senders_to_try = [
        # PRIMARY: subject-based — reliably finds "Security code for your
        # application to <Company>" and skips confirmation emails.
        ("__subject__", 120 if _ci_mode else 45),
        ("greenhouse", 60 if _ci_mode else 25),
        ("lever", 40 if _ci_mode else 20),
        ("ashby", 20 if _ci_mode else 15),
        ("workday", 20 if _ci_mode else 15),
        ("no-reply", 20 if _ci_mode else 15),
        ("noreply", 15 if _ci_mode else 10),
        ("verify", 15 if _ci_mode else 10),
        ("confirm", 15 if _ci_mode else 10),
        ("", 15 if _ci_mode else 10),  # Last resort: any recent email
    ]
    code = None
    for sender, wait_sec in senders_to_try:
        code = get_verification_code(sender_filter=sender, max_wait_seconds=wait_sec, company=company)
        if code:
            break
    
    if code:
        return enter_verification_code(page, code)
    
    return False
