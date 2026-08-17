"""Test Dice.com new 2-step login flow locally before updating CI/CD.

Run: python3 test_dice_login.py

Requirements: pip install undetected-chromedriver selenium setuptools
"""
import os
import time
import subprocess
import re

# Try to detect Chrome version
try:
    # macOS
    out = subprocess.check_output(
        ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '--version']
    ).decode()
    version_main = int(re.search(r'(\d+)\.', out).group(1))
    print(f"✅ Detected Chrome version: {version_main}")
except Exception:
    version_main = None
    print("⚠️  Could not detect Chrome version, using default")

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Get credentials from env or prompt
email = os.environ.get('DICE_EMAIL', '')
password = os.environ.get('DICE_PASSWORD', '')

if not email:
    email = input("Enter Dice email: ")
if not password:
    password = input("Enter Dice password: ")

options = uc.ChromeOptions()
# options.add_argument('--headless=new')  # Uncomment for headless
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')

print("🚀 Launching Chrome...")
driver = uc.Chrome(options=options, version_main=version_main)

try:
    # Step 1: Navigate to login
    print("📍 Going to Dice login...")
    driver.get('https://www.dice.com/dashboard/login')
    time.sleep(4)

    # Step 1: Enter email
    print("📧 Step 1: Entering email...")
    wait = WebDriverWait(driver, 10)
    email_input = wait.until(EC.presence_of_element_located((By.NAME, 'email')))
    email_input.clear()
    email_input.send_keys(email)
    time.sleep(1)

    # Click "Continue with email"
    buttons = driver.find_elements(By.TAG_NAME, 'button')
    for btn in buttons:
        if 'continue with email' in btn.text.lower():
            btn.click()
            print("   ✅ Clicked 'Continue with email'")
            break
    time.sleep(3)

    # Step 2: Enter password
    print("🔑 Step 2: Entering password...")
    password_input = wait.until(EC.presence_of_element_located((By.NAME, 'password')))
    password_input.clear()
    password_input.send_keys(password)
    time.sleep(1)

    # Click "Sign In"
    buttons = driver.find_elements(By.TAG_NAME, 'button')
    for btn in buttons:
        if 'sign in' in btn.text.lower():
            btn.click()
            print("   ✅ Clicked 'Sign In'")
            break
    time.sleep(5)

    # Check if logged in
    page_text = driver.find_element(By.TAG_NAME, 'body').text
    if 'Log Out' in page_text or 'home-feed' in driver.current_url:
        print("🎉 LOGIN SUCCESSFUL!")
        print(f"   URL: {driver.current_url}")
    else:
        print(f"❌ Login may have failed")
        print(f"   URL: {driver.current_url}")
        print(f"   Page text (first 200): {page_text[:200]}")

    input("\nPress Enter to close browser...")

finally:
    driver.quit()
    print("Done.")
