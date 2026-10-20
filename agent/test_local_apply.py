#!/usr/bin/env python3
"""Local test: apply to ONE Greenhouse job with VISIBLE browser.

Usage:
    export GMAIL_USER=bobrikh75@gmail.com
    export GMAIL_APP_PASSWORD=xxxx
    python3 agent/test_local_apply.py

Or without Gmail (just test form fill + code entry UI):
    python3 agent/test_local_apply.py --no-email
"""
import os
import sys
import json
import time
from pathlib import Path

# Add agent/src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from playwright.sync_api import sync_playwright


def main():
    no_email = "--no-email" in sys.argv
    
    # Load profile
    profile_path = Path(__file__).parent / "config" / "profile.json"
    with open(profile_path) as f:
        profile = json.load(f)
    
    # Pick a Greenhouse job URL to test (one that requires verification)
    # Using Affirm as that's what triggered it in CI
    test_url = "https://job-boards.greenhouse.io/affirm/jobs/6472751003"
    
    if len(sys.argv) > 1 and sys.argv[1].startswith("http"):
        test_url = sys.argv[1]
    
    print(f"🧪 LOCAL TEST — Visible browser")
    print(f"   URL: {test_url}")
    print(f"   Email verification: {'ON' if not no_email else 'OFF (manual)'}")
    print(f"   Profile: {profile['first_name']} {profile['last_name']}")
    print()
    
    with sync_playwright() as pw:
        # Launch VISIBLE browser (not headless!)
        browser = pw.chromium.launch(headless=False, slow_mo=500)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        print(f"1️⃣  Navigating to job page...")
        page.goto(test_url, timeout=30000)
        page.wait_for_timeout(3000)
        
        print(f"2️⃣  Looking for application form...")
        # Greenhouse embed pattern
        page.wait_for_timeout(2000)
        
        # Try to fill basic fields
        fields = {
            "#first_name": profile["first_name"],
            "#last_name": profile["last_name"],
            "#email": profile["email"],
            "#phone": profile["phone"],
        }
        
        for sel, val in fields.items():
            try:
                field = page.locator(sel)
                if field.is_visible(timeout=2000):
                    field.fill(val)
                    print(f"   ✅ Filled {sel} = {val}")
            except Exception as e:
                print(f"   ⚠️ Could not fill {sel}: {str(e)[:50]}")
        
        # Upload resume
        resume_path = Path(__file__).parent / "resume.pdf"
        if resume_path.exists():
            try:
                file_input = page.locator('input[type="file"]').first
                if file_input.count() > 0:
                    file_input.set_input_files(str(resume_path))
                    print(f"   ✅ Uploaded resume")
            except Exception as e:
                print(f"   ⚠️ Resume upload: {str(e)[:50]}")
        
        print()
        print(f"3️⃣  Form partially filled. You can fill remaining fields manually.")
        print(f"   Press Enter when ready to SUBMIT...")
        input()
        
        # Find and click submit
        submit_selectors = [
            'button:has-text("Submit application")',
            'button:has-text("Submit Application")',
            'button:has-text("Submit")',
            'input[type="submit"]',
            'button[type="submit"]',
        ]
        
        submitted = False
        for sel in submit_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=1000):
                    print(f"   Clicking: {sel}")
                    btn.click()
                    submitted = True
                    break
            except:
                continue
        
        if not submitted:
            print("   ⚠️ No submit button found. Click it manually.")
            print("   Press Enter after clicking submit...")
            input()
        
        page.wait_for_timeout(3000)
        
        # Check if security code page appeared
        print()
        print(f"4️⃣  Checking for security code input...")
        page.wait_for_timeout(2000)
        
        # Look for OTP boxes
        otp_box = page.locator('#security-input-0')
        single_char = page.locator('input[maxlength="1"]:visible')
        
        if otp_box.is_visible(timeout=3000):
            print(f"   ✅ Found OTP box #security-input-0!")
            print(f"   Total single-char inputs: {single_char.count()}")
            
            if no_email:
                print()
                print(f"5️⃣  Enter the code from your Gmail manually below:")
                code = input("   Code: ").strip()
            else:
                print(f"5️⃣  Reading code from Gmail...")
                from email_code_reader import get_verification_code
                code = get_verification_code(sender_filter="greenhouse", max_wait_seconds=60)
                if not code:
                    print("   ❌ No code received. Enter manually:")
                    code = input("   Code: ").strip()
            
            if code:
                print(f"   Entering code: {code}")
                # THIS IS THE FIX — click first box and TYPE
                otp_box.click()
                page.wait_for_timeout(300)
                page.keyboard.type(code, delay=100)
                print(f"   ✅ Typed code into OTP boxes")
                
                page.wait_for_timeout(1000)
                
                # Click submit
                print(f"6️⃣  Clicking submit after code...")
                for sel in submit_selectors + ['button:has-text("Resubmit")']:
                    try:
                        btn = page.locator(sel).first
                        if btn.is_visible(timeout=1000):
                            btn.click()
                            print(f"   ✅ Clicked: {sel}")
                            break
                    except:
                        continue
                else:
                    print("   Pressing Enter as fallback...")
                    page.keyboard.press("Enter")
                
                page.wait_for_timeout(5000)
                
                # Check result
                text = page.locator("body").inner_text(timeout=5000).lower()
                url = page.url.lower()
                
                if "thank" in text or "thank" in url:
                    print()
                    print("   🎉 SUCCESS! 'Thank you' page detected!")
                    print("   ✅ Check Gmail for confirmation email.")
                else:
                    print()
                    print(f"   ⚠️ Page URL: {page.url}")
                    print(f"   Page text (first 200): {text[:200]}")
        else:
            print("   No OTP boxes found. Page may have:")
            text = page.locator("body").inner_text(timeout=3000).lower()
            if "thank" in text:
                print("   🎉 Already on Thank You page! (no code needed)")
            elif "error" in text or "required" in text:
                print("   ❌ Form errors detected. Fix and retry.")
            else:
                print(f"   URL: {page.url}")
                print(f"   Text: {text[:200]}")
        
        print()
        print("Browser will stay open. Press Enter to close.")
        input()
        browser.close()


if __name__ == "__main__":
    main()
