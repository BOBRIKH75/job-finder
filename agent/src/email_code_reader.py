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
) -> Optional[str]:
    """Poll Gmail IMAP for a FRESH verification code email.
    
    CRITICAL: Each Greenhouse application sends a UNIQUE code. Reusing an old
    code silently fails (page redirects but application is NOT actually submitted).
    
    Strategy:
    1. Search UNSEEN emails from sender
    2. Loop through ALL matches (newest first) looking for a code NOT in _USED_CODES
    3. Mark every processed email as SEEN (prevents re-reads)
    4. If no fresh code found, wait and retry until timeout
    
    Args:
        sender_filter: keyword to match in sender address (e.g., 'greenhouse', 'no-reply')
        max_wait_seconds: how long to wait for the email to arrive
        poll_interval: seconds between IMAP checks
    
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
    
    # STEP 0: Mark ALL today's emails from this sender as SEEN before waiting.
    # The fresh code hasn't arrived yet (Greenhouse sends AFTER submit).
    # Use SINCE (same as main loop) so we're consistent — mark today's old codes as SEEN.
    try:
        from datetime import datetime as _dt
        _today = _dt.now().strftime("%d-%b-%Y")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail_user, gmail_pass)
        mail.select('"[Gmail]/All Mail"')
        if sender_filter:
            search_criteria = f'(SINCE {_today} FROM "{sender_filter}")'
        else:
            search_criteria = f'(SINCE {_today})'
        status, messages = mail.search(None, search_criteria)
        if status == "OK" and messages[0]:
            msg_ids = messages[0].split()
            for msg_id in msg_ids:
                mail.store(msg_id, '+FLAGS', '\\Seen')
            print(f"      📧 Cleared {len(msg_ids)} old email(s) from today — waiting for fresh code only")
        mail.logout()
    except Exception as e:
        print(f"      ⚠️ Could not clear old emails: {str(e)[:40]}")
    
    # Small delay to allow Greenhouse to send the new code
    time.sleep(8)  # Greenhouse typically takes 5-15 seconds to send
    
    start_time = time.time()
    while time.time() - start_time < max_wait_seconds:
        try:
            # Connect to Gmail IMAP
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(gmail_user, gmail_pass)
            mail.select('"[Gmail]/All Mail"')  # Search ALL mail, not just Primary tab
            
            # Search for RECENT emails from the sender (today only)
            from datetime import datetime, timedelta
            today = datetime.now().strftime("%d-%b-%Y")
            if sender_filter:
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
    """Extract verification code from email body."""
    # Common patterns for verification codes
    patterns = [
        r'(?:verification|security|confirm)\s*(?:code|number|pin)\s*(?:is)?\s*[:\-]?\s*(\d{4,8})',
        r'(?:code|pin|OTP)\s*(?:is)?\s*[:\-]?\s*(\d{4,8})',
        r'<strong>(\d{4,8})</strong>',
        r'<b>(\d{4,8})</b>',
        r'\b(\d{6})\b',  # 6-digit code (most common)
    ]
    
    for pattern in patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            return match.group(1)
    
    # Alphanumeric codes — two sub-cases:
    #   1. Standard: mix of digits + letters (e.g., A1B2C3D4)
    #   2. Greenhouse OTP: exactly 8 all-alpha mixed-case (e.g., EEtMwNKJ — NO digits)
    #      Greenhouse tokens are mixed-case with multiple uppercase letters.
    #      Requiring ≥2 uppercase prevents matching sentence-initial capitalized words
    #      like "Security" (1 uppercase) or "Colorado" (1 uppercase).
    for match in re.finditer(r'(?<![A-Za-z0-9])([A-Za-z0-9]{6,8})(?![A-Za-z0-9])', body):
        candidate = match.group(1)
        has_digit = any(c.isdigit() for c in candidate)
        has_letter = any(c.isalpha() for c in candidate)
        if has_digit and has_letter:
            return candidate
        if has_letter and not has_digit and len(candidate) == 8:
            count_upper = sum(1 for c in candidate if c.isupper())
            count_lower = sum(1 for c in candidate if c.islower())
            if count_upper >= 2 and count_lower >= 1:
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


def handle_email_verification(page, skip_detection: bool = False) -> bool:
    """Detect and handle email verification challenge on current page.
    
    Call this when the page shows a verification/security code prompt.
    Returns True if verification was successful.
    
    Args:
        page: Playwright page object
        skip_detection: If True, skip the page text signal check (caller already confirmed
                       this is a verification page, e.g. submit_and_verify returned 
                       email_verification_required). Goes straight to reading code from Gmail.
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
    senders_to_try = [
        ("greenhouse", 45),
        ("lever", 20),
        ("ashby", 15),
        ("workday", 15),
        ("no-reply", 15),
        ("noreply", 10),
        ("verify", 10),
        ("confirm", 10),
        ("", 10),  # Last resort: any recent email
    ]
    code = None
    for sender, wait_sec in senders_to_try:
        code = get_verification_code(sender_filter=sender, max_wait_seconds=wait_sec)
        if code:
            break
    
    if code:
        return enter_verification_code(page, code)
    
    return False
