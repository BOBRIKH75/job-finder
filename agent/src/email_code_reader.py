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


def get_verification_code(
    sender_filter: str = "greenhouse",
    max_wait_seconds: int = 30,
    poll_interval: int = 3,
) -> Optional[str]:
    """Poll Gmail IMAP for a recent verification code email.
    
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
    
    start_time = time.time()
    while time.time() - start_time < max_wait_seconds:
        try:
            # Connect to Gmail IMAP
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(gmail_user, gmail_pass)
            mail.select("inbox")
            
            # Search for recent emails from the sender (last 1 minute)
            # Search recent emails (UNSEEN or within last 2 minutes)
            since_date = (datetime.now() - timedelta(minutes=2)).strftime("%d-%b-%Y")
            if sender_filter:
                search_criteria = f'(UNSEEN FROM "{sender_filter}")'
            else:
                search_criteria = '(UNSEEN)'
            status, messages = mail.search(None, search_criteria)
            
            # If no UNSEEN, try ALL recent from this sender
            if status == "OK" and not messages[0] and sender_filter:
                search_criteria = f'(SINCE {since_date} FROM "{sender_filter}")'
                status, messages = mail.search(None, search_criteria)
            
            if status == "OK" and messages[0]:
                # Get the most recent matching email
                msg_ids = messages[0].split()
                latest_id = msg_ids[-1]  # most recent
                
                status, msg_data = mail.fetch(latest_id, "(RFC822)")
                if status == "OK":
                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)
                    
                    # Extract body text
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                break
                            elif part.get_content_type() == "text/html":
                                body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    else:
                        body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                    
                    # Extract verification code (typically 4-8 digit number or alphanumeric)
                    code = _extract_code(body)
                    if code:
                        print(f"      ✅ Got verification code: {code}")
                        # Mark as read
                        mail.store(latest_id, '+FLAGS', '\\Seen')
                        mail.logout()
                        return code
            
            mail.logout()
        except Exception as e:
            print(f"      ⚠️ Email check error: {str(e)[:60]}")
        
        time.sleep(poll_interval)
    
    print(f"      ❌ No verification email received within {max_wait_seconds}s")
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
    
    # Alphanumeric codes (must contain at least one digit and one letter, 6-8 chars)
    for match in re.finditer(r'(?<![A-Za-z0-9])([A-Z0-9]{6,8})(?![A-Za-z0-9])', body, re.IGNORECASE):
        candidate = match.group(1)
        has_digit = any(c.isdigit() for c in candidate)
        has_letter = any(c.isalpha() for c in candidate)
        if has_digit and has_letter:
            return candidate
    
    return None


def enter_verification_code(page, code: str) -> bool:
    """Enter the verification code on the page and submit.
    
    Greenhouse security code page has a simple text input for the code.
    We try multiple selector strategies from most specific to broadest fallback.
    """
    try:
        # Strategy 1: Try specific selectors for known ATS security code fields
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
    """After entering verification code, click the submit/verify button."""
    page.wait_for_timeout(500)
    for btn_sel in [
        'button:has-text("Submit")',
        'button:has-text("Verify")',
        'button:has-text("Confirm")',
        'button:has-text("Continue")',
        'button:has-text("Submit application")',
        'button:has-text("Resubmit")',
        'input[type="submit"]',
        'button[type="submit"]',
        # Greenhouse specific
        'input[value="Submit Application"]',
        'button[data-testid*="submit"]',
    ]:
        try:
            btn = page.locator(btn_sel).first
            if btn.is_visible(timeout=1000):
                btn.click()
                print(f"      ✅ Clicked submit after code: {btn_sel}")
                page.wait_for_timeout(3000)
                return
        except Exception:
            continue
    print("      ⚠️ No submit button found after entering code — code was entered though")


def handle_email_verification(page) -> bool:
    """Detect and handle email verification challenge on current page.
    
    Call this when the page shows a verification/security code prompt.
    Returns True if verification was successful.
    """
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
