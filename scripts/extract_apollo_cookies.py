#!/usr/bin/env python3
"""
Auto-extract Apollo.io cookies from Chrome on THIS machine.
Saves them as a GitHub secret (APOLLO_COOKIES_B64) automatically.

This runs on the self-hosted runner laptop where you're logged into Apollo in Chrome.
No manual steps — reads Chrome's cookie database directly.

Usage:
  python3 scripts/extract_apollo_cookies.py

Requires: Chrome must have an active Apollo.io session (you logged in before).
"""
import base64
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


def get_chrome_cookie_path() -> Path:
    """Find Chrome's Cookies database file based on OS."""
    system = platform.system()
    
    if system == "Darwin":  # macOS
        paths = [
            Path.home() / "Library/Application Support/Google/Chrome/Default/Cookies",
            Path.home() / "Library/Application Support/Google/Chrome/Profile 1/Cookies",
        ]
    elif system == "Linux":  # Linux (GitHub runner)
        paths = [
            Path.home() / ".config/google-chrome/Default/Cookies",
            Path.home() / ".config/chromium/Default/Cookies",
            Path.home() / "snap/chromium/common/chromium/Default/Cookies",
        ]
    elif system == "Windows":
        local_app = os.environ.get("LOCALAPPDATA", "")
        paths = [
            Path(local_app) / "Google/Chrome/User Data/Default/Network/Cookies",
            Path(local_app) / "Google/Chrome/User Data/Default/Cookies",
        ]
    else:
        paths = []
    
    for p in paths:
        if p.exists():
            return p
    
    return None


def extract_apollo_cookies(cookie_db: Path) -> list:
    """Read Apollo.io cookies from Chrome's SQLite database.
    
    Note: Chrome encrypts cookie values on macOS (Keychain) and Windows (DPAPI).
    On Linux (GitHub runner), they may be unencrypted or use basic encryption.
    """
    # Copy the database (Chrome locks it while running)
    tmp_db = Path(tempfile.mktemp(suffix=".db"))
    shutil.copy2(cookie_db, tmp_db)
    
    cookies = []
    try:
        conn = sqlite3.connect(str(tmp_db))
        cursor = conn.cursor()
        
        # Query Apollo cookies
        cursor.execute("""
            SELECT name, value, host_key, path, expires_utc, is_secure, is_httponly
            FROM cookies
            WHERE host_key LIKE '%apollo.io%'
        """)
        
        for row in cursor.fetchall():
            name, value, domain, path, expires, secure, httponly = row
            
            # Skip if value is encrypted (empty string = encrypted on macOS)
            if not value:
                continue
                
            cookies.append({
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
                "secure": bool(secure),
                "httpOnly": bool(httponly),
            })
        
        conn.close()
    finally:
        tmp_db.unlink(missing_ok=True)
    
    return cookies


def decrypt_macos_cookies(cookie_db: Path) -> list:
    """On macOS, use the `security` command to get the Chrome encryption key,
    then decrypt cookie values. Falls back to browser-based extraction if this fails."""
    try:
        # Get Chrome's encryption key from Keychain
        result = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return []
        
        key_password = result.stdout.strip()
        
        # Derive the actual key (PBKDF2)
        import hashlib
        key = hashlib.pbkdf2_hmac(
            "sha1", key_password.encode(), b"saltysalt", 1003, dklen=16
        )
        
        # Copy and read database
        tmp_db = Path(tempfile.mktemp(suffix=".db"))
        shutil.copy2(cookie_db, tmp_db)
        
        conn = sqlite3.connect(str(tmp_db))
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, encrypted_value, host_key, path, expires_utc, is_secure, is_httponly
            FROM cookies
            WHERE host_key LIKE '%apollo.io%'
        """)
        
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
        
        cookies = []
        for row in cursor.fetchall():
            name, encrypted_value, domain, path, expires, secure, httponly = row
            
            if not encrypted_value:
                continue
            
            # Chrome macOS encryption: v10 + AES-CBC
            if encrypted_value[:3] == b"v10":
                iv = b" " * 16
                cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
                decryptor = cipher.decryptor()
                decrypted = decryptor.update(encrypted_value[3:]) + decryptor.finalize()
                # Remove PKCS7 padding
                padding = decrypted[-1]
                value = decrypted[:-padding].decode("utf-8", errors="ignore")
            else:
                value = encrypted_value.decode("utf-8", errors="ignore")
            
            if value:
                cookies.append({
                    "name": name,
                    "value": value,
                    "domain": domain,
                    "path": path,
                    "secure": bool(secure),
                    "httpOnly": bool(httponly),
                })
        
        conn.close()
        tmp_db.unlink(missing_ok=True)
        return cookies
        
    except ImportError:
        print("   ⚠️  cryptography package not installed (pip install cryptography)")
        return []
    except Exception as e:
        print(f"   ⚠️  macOS decryption failed: {e}")
        return []


def save_as_github_secret(cookies: list) -> bool:
    """Save cookies as APOLLO_COOKIES_B64 GitHub secret."""
    cookies_json = json.dumps(cookies)
    encoded = base64.b64encode(cookies_json.encode()).decode()
    
    try:
        result = subprocess.run(
            ["gh", "secret", "set", "APOLLO_COOKIES_B64", "--repo", "BOBRIKH75/job-finder"],
            input=encoded, text=True, capture_output=True
        )
        return result.returncode == 0
    except Exception as e:
        print(f"   ❌ gh secret set failed: {e}")
        return False


def main():
    print("🍪 Apollo Cookie Extractor")
    print("═══════════════════════════")
    print("")
    
    # Find Chrome cookies
    cookie_db = get_chrome_cookie_path()
    if not cookie_db:
        # Apollo is an OPTIONAL recruiter-email source. When this runner has no
        # Chrome profile with a live Apollo login, we simply skip — the pipeline
        # falls through to Hunter.io / Snov.io / job-description extraction.
        # Exit 0 (not 1) so the workflow stays green instead of a false red-X.
        print("⏭️  Chrome cookie database not found — skipping Apollo refresh (optional source).")
        print("   To enable Apollo: log into Apollo.io in Chrome on this runner, then re-run.")
        sys.exit(0)
    
    print(f"   Chrome DB: {cookie_db}")
    
    # Try to extract
    system = platform.system()
    cookies = []
    
    if system == "Darwin":
        print("   Platform: macOS — trying decryption...")
        cookies = decrypt_macos_cookies(cookie_db)
        if not cookies:
            # Fallback: try unencrypted values
            cookies = extract_apollo_cookies(cookie_db)
    else:
        cookies = extract_apollo_cookies(cookie_db)
    
    if not cookies:
        # Expected when the runner's Chrome has no live Apollo session or the
        # cookies are Keychain-encrypted and unreadable from the runner process.
        # Apollo is OPTIONAL — skip gracefully (exit 0) so the workflow stays
        # green; recruiter_finder falls through to Hunter/Snov/job-desc sources.
        print("")
        print("⏭️  No readable Apollo cookies — skipping (optional source, pipeline uses Hunter/Snov instead).")
        print("   To enable Apollo: (1) log into Apollo.io in Chrome on this runner,")
        print("   (2) install 'cryptography', or (3) set APOLLO_COOKIES_B64 manually.")
        sys.exit(0)
    
    print(f"   ✅ Found {len(cookies)} Apollo cookies")
    
    # Key cookies to verify
    key_names = {"_session_id", "remember_token", "remember_token_leadgenie_v2", "ZP_Pricing_Split_Test"}
    found_keys = {c["name"] for c in cookies} & key_names
    print(f"   Session cookies: {len(found_keys)} key cookies found")
    
    # Save to GitHub secret
    print("")
    print("   Saving to GitHub secret APOLLO_COOKIES_B64...")
    if save_as_github_secret(cookies):
        print("   ✅ APOLLO_COOKIES_B64 secret set!")
        print("")
        print("🎉 Done! Apollo scraper will use these cookies on next run.")
        print("   Cookies auto-refresh every 7 days (TTL in apollo_scraper.py)")
    else:
        # Fallback: print for manual set
        cookies_json = json.dumps(cookies)
        encoded = base64.b64encode(cookies_json.encode()).decode()
        print("   ⚠️  Auto-set failed. Set manually:")
        print(f"   gh secret set APOLLO_COOKIES_B64 --body '{encoded[:50]}...'")


if __name__ == "__main__":
    main()
