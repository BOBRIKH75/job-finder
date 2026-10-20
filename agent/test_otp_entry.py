#!/usr/bin/env python3
"""Test OTP code entry on Greenhouse — FULLY AUTOMATIC, no human input.

This script:
1. Opens a Greenhouse job page (visible browser)
2. Fills ALL required fields automatically  
3. Submits the form
4. When security code boxes appear, tests typing into them
5. Verifies ALL 8 boxes got filled
6. Logs everything

Run: python3 agent/test_otp_entry.py
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from playwright.sync_api import sync_playwright

LOG = "/tmp/otp_test_results.txt"

def log(msg):
    print(msg, flush=True)
    with open(LOG, "a") as f:
        f.write(msg + "\n")

def fill_greenhouse_form(page, profile):
    """Fill all basic + custom Greenhouse fields."""
    # Basic fields
    basics = {
        "#first_name": profile["first_name"],
        "#last_name": profile["last_name"],  
        "#email": profile["email"],
        "#phone": profile["phone"],
    }
    for sel, val in basics.items():
        try:
            f = page.locator(sel)
            if f.is_visible(timeout=2000):
                f.fill(val)
        except:
            pass
    
    # Resume upload
    resume = Path(__file__).parent / "resume.pdf"
    if resume.exists():
        try:
            uploads = page.locator('input[type="file"]')
            for i in range(uploads.count()):
                uploads.nth(i).set_input_files(str(resume))
        except:
            pass
    
    # LinkedIn
    try:
        for sel in ['input[id*="linkedin" i]', 'input[placeholder*="linkedin" i]', 'input[aria-label*="linkedin" i]']:
            f = page.locator(sel).first
            if f.is_visible(timeout=500):
                f.fill(profile.get("linkedin", "https://www.linkedin.com/in/bobrikh75/"))
                break
    except:
        pass
    
    # Fill all remaining empty text inputs with reasonable defaults
    try:
        inputs = page.locator('input[type="text"]:visible')
        for i in range(inputs.count()):
            inp = inputs.nth(i)
            val = inp.input_value()
            if not val:  # Empty
                iid = inp.get_attribute('id') or ''
                placeholder = (inp.get_attribute('placeholder') or '').lower()
                # Skip OTP/security inputs
                if 'security' in iid or 'otp' in iid:
                    continue
                if 'github' in iid or 'github' in placeholder:
                    inp.fill("https://github.com/BOBRIKH75")
                elif 'website' in iid or 'portfolio' in placeholder or 'website' in placeholder:
                    inp.fill("https://www.linkedin.com/in/bobrikh75/")
                elif 'salary' in placeholder or 'compensation' in placeholder or 'rate' in placeholder:
                    inp.fill("95000")
                elif 'city' in placeholder or 'location' in placeholder:
                    inp.fill("Parker, CO")
                else:
                    inp.fill("N/A")
    except:
        pass
    
    # Handle select/dropdowns — pick first non-empty option
    try:
        selects = page.locator('select:visible')
        for i in range(selects.count()):
            sel = selects.nth(i)
            try:
                # Get options
                options = sel.locator('option')
                for j in range(1, options.count()):  # skip first (usually placeholder)
                    opt_val = options.nth(j).get_attribute('value')
                    if opt_val:
                        sel.select_option(value=opt_val)
                        break
            except:
                pass
    except:
        pass
    
    # Click-based dropdowns (Greenhouse custom)
    try:
        # Look for "Select..." buttons and click first option
        select_btns = page.locator('button:has-text("Select")')
        for i in range(select_btns.count()):
            try:
                btn = select_btns.nth(i)
                if btn.is_visible(timeout=300):
                    btn.click()
                    page.wait_for_timeout(500)
                    # Click first option in dropdown
                    option = page.locator('[role="option"], [class*="option"]').first
                    if option.is_visible(timeout=500):
                        option.click()
                        page.wait_for_timeout(300)
            except:
                pass
    except:
        pass


def test_otp_boxes(page, test_code="ABCD1234"):
    """Test that keyboard.type() fills all OTP boxes. Returns True/False."""
    log(f"\n   🧪 Testing OTP entry with code: {test_code}")
    
    # Find first OTP box
    otp_first = page.locator('#security-input-0')
    if not otp_first.is_visible(timeout=3000):
        # Try alternative selectors
        otp_first = page.locator('input[maxlength="1"]:visible').first
        if not otp_first.is_visible(timeout=1000):
            log("   ❌ No OTP boxes found!")
            return False
    
    log(f"   ✅ Found OTP first box")
    
    # Click and type
    otp_first.click()
    page.wait_for_timeout(500)
    page.keyboard.type(test_code, delay=150)
    page.wait_for_timeout(1000)
    
    # VERIFY: check each box has a value
    filled_count = 0
    for i in range(8):
        try:
            box = page.locator(f'#security-input-{i}')
            if box.is_visible(timeout=300):
                val = box.input_value()
                expected_char = test_code[i] if i < len(test_code) else ''
                if val:
                    filled_count += 1
                    log(f"      Box #{i}: '{val}' (expected: '{expected_char}') {'✅' if val == expected_char else '⚠️'}")
                else:
                    log(f"      Box #{i}: EMPTY ❌ (expected: '{expected_char}')")
        except:
            break
    
    log(f"\n   Result: {filled_count}/{len(test_code)} boxes filled")
    
    if filled_count == len(test_code):
        log(f"   🎉 SUCCESS — all boxes filled correctly!")
        return True
    elif filled_count > 0:
        log(f"   ⚠️ PARTIAL — some boxes filled but not all")
        return False
    else:
        log(f"   ❌ FAILED — no boxes filled (keyboard.type didn't work)")
        return False


def test_submit_button(page):
    """Verify the submit button is findable after code entry."""
    log(f"\n   🧪 Testing submit button detection...")
    
    selectors = [
        'button:has-text("Submit application")',
        'button:has-text("Submit Application")', 
        'button:has-text("Submit")',
        'input[type="submit"]',
        'button[type="submit"]',
    ]
    
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1000):
                text = btn.inner_text(timeout=1000).strip()[:50]
                log(f"   ✅ Found button: '{text}' via selector: {sel}")
                return True
        except:
            continue
    
    log(f"   ❌ No submit button found with any selector!")
    return False


def main():
    profile_path = Path(__file__).parent / "config" / "profile.json"
    with open(profile_path) as f:
        profile = json.load(f)
    
    test_url = "https://job-boards.greenhouse.io/affirm/jobs/7636414003"
    if len(sys.argv) > 1 and sys.argv[1].startswith("http"):
        test_url = sys.argv[1]
    
    with open(LOG, "w") as f:
        f.write("=== OTP Entry Test ===\n\n")
    
    log(f"🔬 OTP ENTRY TEST")
    log(f"   URL: {test_url}")
    log(f"   Goal: Verify keyboard.type() fills all 8 OTP boxes")
    
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=300)
        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        
        # Navigate
        log(f"\n▶ STEP 1: Navigate to job page")
        page.goto(test_url, timeout=30000)
        page.wait_for_timeout(3000)
        
        if "error=true" in page.url:
            log(f"   ❌ Job page returned error! URL: {page.url}")
            log(f"   Try a different URL.")
            browser.close()
            return
        
        log(f"   ✅ Page loaded: {page.url}")
        
        # Fill form
        log(f"\n▶ STEP 2: Fill ALL form fields")
        fill_greenhouse_form(page, profile)
        page.wait_for_timeout(2000)
        log(f"   ✅ Form filled")
        
        # Scroll down and screenshot
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)
        
        # Submit
        log(f"\n▶ STEP 3: Submit form")
        for sel in ['button:has-text("Submit application")', 'button:has-text("Submit")', 'button[type="submit"]']:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=1000):
                    btn.scroll_into_view_if_needed()
                    page.wait_for_timeout(300)
                    btn.click()
                    log(f"   ✅ Clicked: {sel}")
                    break
            except:
                continue
        
        # Wait for response
        page.wait_for_timeout(5000)
        
        # Check state
        log(f"\n▶ STEP 4: Check page state after submit")
        text = page.locator('body').inner_text(timeout=5000).lower()
        
        if 'security code' in text or 'verification code' in text:
            log(f"   ✅ SECURITY CODE PAGE APPEARED!")
            
            # Test OTP entry
            log(f"\n▶ STEP 5: Test OTP box typing")
            otp_success = test_otp_boxes(page, "TESTCODE")  # 8 chars
            
            # Test submit button
            log(f"\n▶ STEP 6: Test submit button")
            btn_success = test_submit_button(page)
            
            # Summary
            log(f"\n{'='*60}")
            log(f"   RESULTS:")
            log(f"   OTP typing:     {'✅ PASS' if otp_success else '❌ FAIL'}")
            log(f"   Submit button:  {'✅ PASS' if btn_success else '❌ FAIL'}")
            log(f"{'='*60}")
            
        elif 'required' in text or 'error' in text:
            log(f"   ⚠️ Form validation errors — missing required fields")
            log(f"   Need to fill more fields. Checking what's missing...")
            
            # Find error messages
            try:
                errors = page.locator('[class*="error"]:visible, [aria-invalid="true"]:visible')
                log(f"   Error elements: {errors.count()}")
                for i in range(min(errors.count(), 10)):
                    txt = errors.nth(i).inner_text(timeout=500).strip()[:60]
                    if txt:
                        log(f"      - {txt}")
            except:
                pass
            
        elif 'thank' in text:
            log(f"   🎉 THANK YOU PAGE — already submitted!")
        else:
            log(f"   ❓ Unknown state")
            log(f"   URL: {page.url}")
            log(f"   Text: {text[:300]}")
        
        # Keep browser open
        log(f"\n   Browser open for 60 seconds...")
        page.wait_for_timeout(60000)
        browser.close()


if __name__ == "__main__":
    main()
