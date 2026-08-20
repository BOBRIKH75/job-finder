#!/usr/bin/env python3
"""
Email Verifier — checks if an email address actually exists via SMTP.

NO API key needed. FREE. Works by:
1. DNS MX lookup (find the mail server)
2. SMTP handshake (ask "does this mailbox exist?")
3. Returns True/False without sending any email

Usage:
    from verify_email import verify_email, find_valid_email
    
    # Check single email
    exists = verify_email("recruiting@skiltrek.com")
    
    # Find which pattern works for a company
    email = find_valid_email("skiltrek.com")  # tries common patterns
"""

import socket
import smtplib
import dns.resolver
import re
from typing import Optional


def get_mx_record(domain: str) -> Optional[str]:
    """Get the MX (mail exchange) server for a domain."""
    try:
        records = dns.resolver.resolve(domain, 'MX')
        # Get highest priority MX record
        mx = sorted(records, key=lambda r: r.preference)[0]
        return str(mx.exchange).rstrip('.')
    except Exception:
        return None


def verify_email(email: str, timeout: int = 10) -> bool:
    """Verify an email address exists via SMTP handshake.
    
    Returns True if the mail server confirms the mailbox exists.
    Returns False if rejected or unreachable.
    Does NOT send any email.
    """
    if not email or '@' not in email:
        return False
    
    domain = email.split('@')[1]
    
    # Step 1: Find the mail server
    mx_host = get_mx_record(domain)
    if not mx_host:
        return False
    
    # Step 2: SMTP handshake
    try:
        smtp = smtplib.SMTP(timeout=timeout)
        smtp.connect(mx_host, 25)
        smtp.helo('verify.local')
        smtp.mail('verify@gmail.com')
        code, _ = smtp.rcpt(email)
        smtp.quit()
        
        # 250 = address exists, 251 = forwarded (still valid)
        return code in (250, 251)
    except smtplib.SMTPServerDisconnected:
        return False
    except smtplib.SMTPConnectError:
        return False
    except socket.timeout:
        return False
    except Exception:
        return False


def find_valid_email(domain: str, first_name: str = "", last_name: str = "") -> Optional[str]:
    """Try common email patterns for a company and return the first verified one.
    
    If first_name/last_name provided, tries personal patterns first.
    Otherwise tries generic recruiting emails.
    """
    patterns = []
    
    # Personal patterns (if name provided)
    if first_name and last_name:
        f = first_name.lower().strip()
        l = last_name.lower().strip()
        patterns.extend([
            f"{f}.{l}@{domain}",
            f"{f}{l}@{domain}",
            f"{f[0]}{l}@{domain}",
            f"{f}@{domain}",
            f"{f[0]}.{l}@{domain}",
        ])
    
    # Generic recruiting patterns (most staffing firms have these)
    patterns.extend([
        f"recruiting@{domain}",
        f"careers@{domain}",
        f"jobs@{domain}",
        f"hr@{domain}",
        f"resumes@{domain}",
        f"staffing@{domain}",
        f"info@{domain}",
    ])
    
    # Verify each pattern
    for email in patterns:
        if verify_email(email):
            return email
    
    return None


def verify_and_filter(emails: list[str]) -> list[str]:
    """Take a list of emails, return only the verified ones."""
    verified = []
    for email in emails:
        if verify_email(email):
            verified.append(email)
    return verified


if __name__ == "__main__":
    # Test with known domains
    test_cases = [
        "recruiting@skiltrek.com",
        "careers@cognizant.com",
        "info@pyramidci.com",
        "fake12345@nonexistentdomain99.com",
    ]
    for email in test_cases:
        result = verify_email(email)
        print(f"{'✅' if result else '❌'} {email}")
