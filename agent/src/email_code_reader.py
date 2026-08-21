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
    """Enter the verification code on the page and submit."""
    try:
        # Look for verification code input field
        selectors = [
            'input[name*="code"]',
            'input[name*="verification"]',
            'input[name*="otp"]',
            'input[name*="pin"]',
            'input[name*="token"]',
            'input[placeholder*="code"]',
            'input[placeholder*="verification"]',
            'input[type="text"][maxlength="6"]',
            'input[type="number"]',
            '#verification_code',
            '#security_code',
        ]
        
        for sel in selectors:
            try:
                field = page.locator(sel).first
                if field.is_visible(timeout=1000):
                    field.fill(code)
                    print(f"      ✅ Entered code in: {sel}")
                    
                    # Click submit/verify button
                    for btn_sel in [
                        'button:has-text("Verify")',
                        'button:has-text("Submit")',
                        'button:has-text("Confirm")',
                        'button:has-text("Continue")',
                        'input[type="submit"]',
                        'button[type="submit"]',
                    ]:
                        try:
                            btn = page.locator(btn_sel).first
                            if btn.is_visible(timeout=1000):
                                btn.click()
                                page.wait_for_timeout(2000)
                                return True
                        except Exception:
                            continue
                    return True
            except Exception:
                continue
        
        print("      ⚠️ Could not find verification code input field")
        return False
    except Exception as e:
        print(f"      ⚠️ Error entering code: {str(e)[:60]}")
        return False


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
    
    # Try Greenhouse-specific sender first (wait longer — emails can take 30-60 sec)
    code = get_verification_code(sender_filter="greenhouse", max_wait_seconds=60)
    if not code:
        code = get_verification_code(sender_filter="no-reply", max_wait_seconds=20)
    if not code:
        code = get_verification_code(sender_filter="verify", max_wait_seconds=10)
    if not code:
        # Last resort: any recent email with a 6-digit code
        code = get_verification_code(sender_filter="", max_wait_seconds=10)
    
    if code:
        return enter_verification_code(page, code)
    
    return False
