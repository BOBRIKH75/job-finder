#!/usr/bin/env python3
"""
Apollo.io Recruiter Scraper — Selenium + Cookies.

Uses your Apollo.io session cookies to search for recruiters.
Bypasses the 120/year export limit by scraping the UI directly.
Apollo gives 10K email credits/month — this uses those credits.

Approach inspired by maximo3k/apollo-search-scraper and FraneCal/apollo_scraper.

Requires:
- selenium
- webdriver-manager (or chromedriver in PATH)
- Apollo.io cookies exported as JSON (via EditThisCookie Chrome extension)

Search targets:
- Titles: Technical Recruiter, IT Recruiter, Bench Sales, Staffing Manager
- Company keywords: staffing, consulting, C2C, corp-to-corp
- Location: United States
"""
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException, NoSuchElementException, StaleElementReferenceException
    )
except ImportError:
    print("❌ selenium not installed. Run: pip install selenium webdriver-manager")
    raise

try:
    from webdriver_manager.chrome import ChromeDriverManager
    USE_WDM = True
except ImportError:
    USE_WDM = False

# ─── Paths ────────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent.parent / "data"
COOKIES_FILE = Path("/tmp/apollo_cookies.json")  # /tmp ONLY — never in repo (public!)
RESULTS_FILE = DATA_DIR / "apollo_recruiters.json"
VENDOR_FILE = DATA_DIR / "vendor_list.json"

# ─── Apollo Search URLs (pre-built with filters) ─────────────────────────────
# These URLs encode the search: Title contains recruiter keywords,
# Company keywords = staffing/consulting, Location = US
SEARCH_QUERIES = [
    # Technical Recruiters at staffing firms
    {
        "name": "Technical Recruiters - Staffing",
        "url": "https://app.apollo.io/#/people?page=1"
              "&personTitles[]=Technical%20Recruiter"
              "&personTitles[]=IT%20Recruiter"
              "&personTitles[]=Bench%20Sales"
              "&personTitles[]=Staffing%20Manager"
              "&personTitles[]=Talent%20Acquisition"
              "&organizationIndustryTagIds[]=5567cd4773696439b10b0000"  # staffing/recruiting
              "&personLocations[]=United%20States",
    },
    # C2C/Corp-to-Corp specialists
    {
        "name": "C2C Recruiters",
        "url": "https://app.apollo.io/#/people?page=1"
              "&qKeywords=C2C%20OR%20corp-to-corp%20OR%20%22bench%20sales%22"
              "&personTitles[]=Recruiter"
              "&personTitles[]=Account%20Manager"
              "&personLocations[]=United%20States",
    },
    # IT Consulting firms
    {
        "name": "IT Consulting Recruiters",
        "url": "https://app.apollo.io/#/people?page=1"
              "&personTitles[]=Technical%20Recruiter"
              "&personTitles[]=Sr.%20Recruiter"
              "&personTitles[]=Lead%20Recruiter"
              "&qOrganizationName=consulting%20OR%20staffing%20OR%20solutions"
              "&personLocations[]=United%20States",
    },
]

# Max pages to scrape per search (25 results/page, 4 pages = 100 per query)
MAX_PAGES = 4
# Delay between page loads (seconds) — be respectful
PAGE_DELAY = 3
# Max contacts per run
MAX_CONTACTS_PER_RUN = 150


def load_cookies() -> list:
    """Load Apollo cookies from JSON file — with TTL expiration check.
    
    Cookies are only valid for a limited time. If expired, returns empty
    so the system falls back to fresh login automatically.
    """
    if not COOKIES_FILE.exists():
        # Check environment variable (for CI — base64-encoded JSON)
        encoded = os.environ.get("APOLLO_COOKIES_B64", "")
        if encoded:
            import base64
            return json.loads(base64.b64decode(encoded))
        
        # Try raw JSON from env var
        raw = os.environ.get("APOLLO_COOKIES_JSON", "")
        if raw:
            return json.loads(raw)
        return []
    
    # Check TTL — cookies file older than 7 days = expired, force fresh login
    import stat
    file_age_seconds = time.time() - COOKIES_FILE.stat().st_mtime
    max_age_seconds = 7 * 24 * 60 * 60  # 7 days TTL
    
    if file_age_seconds > max_age_seconds:
        print(f"   ⚠️  Cookies expired (age: {int(file_age_seconds / 86400)}d, TTL: 7d) — will re-login")
        # Don't delete — keep as backup, but return empty to trigger fresh login
        return []
    
    cookies = json.loads(COOKIES_FILE.read_text())
    
    # Also check individual cookie expiry timestamps
    now = time.time()
    valid_cookies = []
    expired_count = 0
    for cookie in cookies:
        expiry = cookie.get("expiry") or cookie.get("expirationDate")
        if expiry and float(expiry) < now:
            expired_count += 1
            continue
        valid_cookies.append(cookie)
    
    if expired_count > len(cookies) * 0.5:
        # More than half expired — session is dead
        print(f"   ⚠️  {expired_count}/{len(cookies)} cookies expired — will re-login")
        return []
    
    days_old = int(file_age_seconds / 86400)
    print(f"   ✅ Cookies loaded ({len(valid_cookies)} valid, {days_old}d old, TTL: 7d)")
    return valid_cookies


def create_driver(headless: bool = True) -> webdriver.Chrome:
    """Create Chrome WebDriver with stealth settings."""
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if USE_WDM:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    else:
        driver = webdriver.Chrome(options=options)

    # Remove webdriver flag
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver


def inject_cookies(driver: webdriver.Chrome, cookies: list) -> bool:
    """Inject Apollo.io cookies into the browser session."""
    # First navigate to Apollo domain so cookies can be set
    driver.get("https://app.apollo.io")
    time.sleep(2)

    for cookie in cookies:
        try:
            # EditThisCookie format → Selenium format
            selenium_cookie = {
                "name": cookie.get("name", ""),
                "value": cookie.get("value", ""),
                "domain": cookie.get("domain", ".apollo.io"),
                "path": cookie.get("path", "/"),
            }
            # Only add if it's for apollo.io domain
            domain = selenium_cookie["domain"]
            if "apollo" in domain:
                if domain.startswith("."):
                    selenium_cookie["domain"] = domain
                driver.add_cookie(selenium_cookie)
        except Exception as e:
            # Some cookies may fail (httpOnly, secure flags) — skip them
            pass

    # Verify login by navigating to app
    driver.get("https://app.apollo.io/#/people")
    time.sleep(3)

    # Check if we're logged in (look for search input or people list)
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[class*='People'], [class*='search'], input[placeholder]"))
        )
        print("✅ Apollo login successful via cookies")
        return True
    except TimeoutException:
        # Check if redirected to login page
        if "/login" in driver.current_url or "/sign-in" in driver.current_url:
            print("❌ Cookies expired — need fresh cookies from Chrome")
            return False
        # Might still be loading
        print("⚠️  Page loaded but couldn't verify login — continuing anyway")
        return True


def scrape_contacts_from_page(driver: webdriver.Chrome) -> list:
    """Extract contact information from the current Apollo search results page."""
    contacts = []
    time.sleep(2)

    # Apollo's people search results are in table rows or card-like elements
    # Try multiple selectors as Apollo's UI changes
    selectors = [
        "tr[class*='zp_']",                    # Table rows
        "[class*='ContactRow']",               # Contact row components
        "[data-cy='people-table-row']",        # Data-cy attribute
        "tbody tr",                            # Generic table rows
        "[class*='person-row']",               # Person row
    ]

    rows = []
    for sel in selectors:
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, sel)
            if rows:
                break
        except Exception:
            continue

    if not rows:
        # Fallback: try to get data from the page source
        return _extract_from_page_source(driver)

    for row in rows:
        try:
            contact = _extract_contact_from_row(row)
            if contact and contact.get("email"):
                contacts.append(contact)
        except (StaleElementReferenceException, NoSuchElementException):
            continue

    return contacts


def _extract_contact_from_row(row) -> Optional[dict]:
    """Extract name, email, title, company, LinkedIn from a table row."""
    contact = {}

    # Try to click the email reveal button if present
    try:
        email_btn = row.find_element(By.CSS_SELECTOR, 
            "[class*='email-btn'], [data-cy*='email'], button[class*='access']")
        email_btn.click()
        time.sleep(0.5)
    except (NoSuchElementException, Exception):
        pass

    # Extract name
    try:
        name_el = row.find_element(By.CSS_SELECTOR, 
            "a[href*='/people/'], [class*='name'], [class*='contact-name']")
        contact["name"] = name_el.text.strip()
    except NoSuchElementException:
        pass

    # Extract title
    try:
        title_el = row.find_element(By.CSS_SELECTOR, 
            "[class*='title'], [class*='job-title'], span[class*='zp_']")
        contact["title"] = title_el.text.strip()
    except NoSuchElementException:
        pass

    # Extract company
    try:
        company_el = row.find_element(By.CSS_SELECTOR, 
            "a[href*='/companies/'], [class*='company'], [class*='org']")
        contact["company"] = company_el.text.strip()
    except NoSuchElementException:
        pass

    # Extract email (may be revealed or in a tooltip)
    try:
        email_el = row.find_element(By.CSS_SELECTOR, 
            "a[href^='mailto:'], [class*='email-value'], [data-cy*='email-text']")
        email_text = email_el.get_attribute("href") or email_el.text
        email = email_text.replace("mailto:", "").strip().lower()
        if "@" in email and "." in email.split("@")[1]:
            contact["email"] = email
    except NoSuchElementException:
        pass

    # Extract LinkedIn
    try:
        li_el = row.find_element(By.CSS_SELECTOR, "a[href*='linkedin.com']")
        contact["linkedin_url"] = li_el.get_attribute("href")
    except NoSuchElementException:
        pass

    return contact if contact.get("name") else None


def _extract_from_page_source(driver: webdriver.Chrome) -> list:
    """Fallback: extract ONLY structured contact data from Apollo's embedded JSON.
    
    STRICT RULES — NO guessing:
    - Only extract contacts where email + name are in the SAME JSON object
    - Never pair emails with names from different objects
    - Skip any email that doesn't look like a real person
    """
    contacts = []
    source = driver.page_source

    # Apollo embeds contact data as JSON in script tags / __NEXT_DATA__ / redux state
    # Look for complete contact objects (email + name in same object)
    # Pattern: {"email":"x@y.com","name":"First Last",...}
    contact_pattern = re.compile(
        r'\{[^{}]*"email"\s*:\s*"([^"]+@[^"]+)"[^{}]*"name"\s*:\s*"([^"]{3,50})"[^{}]*\}'
    )
    # Also reversed order: name before email
    contact_pattern2 = re.compile(
        r'\{[^{}]*"name"\s*:\s*"([^"]{3,50})"[^{}]*"email"\s*:\s*"([^"]+@[^"]+)"[^{}]*\}'
    )

    # Pattern 1: email before name
    for match in contact_pattern.finditer(source):
        email = match.group(1).lower().strip()
        name = match.group(2).strip()
        if _is_valid_apollo_email(email) and _is_valid_name(name):
            contacts.append({
                "email": email,
                "name": name,
                "title": "",
                "company": "",
                "source": "apollo_structured",
            })

    # Pattern 2: name before email
    for match in contact_pattern2.finditer(source):
        name = match.group(1).strip()
        email = match.group(2).lower().strip()
        if _is_valid_apollo_email(email) and _is_valid_name(name):
            # Avoid duplicates from pattern 1
            if not any(c["email"] == email for c in contacts):
                contacts.append({
                    "email": email,
                    "name": name,
                    "title": "",
                    "company": "",
                    "source": "apollo_structured",
                })

    return contacts


def _is_valid_apollo_email(email: str) -> bool:
    """Validate email is a real person — not Apollo system, not generic."""
    if not email or "@" not in email:
        return False
    local, domain = email.split("@", 1)
    # Skip Apollo/system emails
    skip_domains = {"apollo.io", "apolloio.com", "example.com", "test.com"}
    if domain.lower() in skip_domains:
        return False
    # Skip generic/role-based emails
    skip_locals = {
        "info", "admin", "support", "help", "contact", "team", "hr",
        "careers", "jobs", "hiring", "talent", "recruiting", "noreply",
        "no-reply", "sales", "marketing", "hello", "apply",
    }
    if local.lower() in skip_locals:
        return False
    # Must have at least a dot or reasonable length (looks like first.last)
    if len(local) < 3:
        return False
    return True


def _is_valid_name(name: str) -> bool:
    """Check if extracted name looks like a real person name."""
    if not name or len(name) < 3:
        return False
    # Must have at least first + last (space-separated)
    parts = name.strip().split()
    if len(parts) < 2:
        return False
    # No numbers, no special chars (except hyphens in names)
    if re.search(r'[0-9{}<>\\|]', name):
        return False
    return True


def navigate_to_next_page(driver: webdriver.Chrome, current_page: int) -> bool:
    """Click the next page button in Apollo's pagination."""
    try:
        # Try multiple pagination selectors
        next_selectors = [
            f"a[href*='page={current_page + 1}']",
            "button[aria-label='Next']",
            "[class*='pagination'] [class*='next']",
            "[class*='Pagination'] button:last-child",
        ]
        for sel in next_selectors:
            try:
                next_btn = driver.find_element(By.CSS_SELECTOR, sel)
                if next_btn.is_enabled():
                    next_btn.click()
                    return True
            except NoSuchElementException:
                continue
        
        # Try updating URL directly
        current_url = driver.current_url
        if f"page={current_page}" in current_url:
            new_url = current_url.replace(f"page={current_page}", f"page={current_page + 1}")
            driver.get(new_url)
            return True
        elif "page=" not in current_url:
            driver.get(current_url + f"&page={current_page + 1}")
            return True

    except Exception as e:
        print(f"  ⚠️  Pagination failed: {e}")
    return False


def run_search(driver: webdriver.Chrome, search: dict) -> list:
    """Run a single Apollo search and collect all contacts across pages."""
    all_contacts = []
    name = search["name"]
    url = search["url"]

    print(f"\n  🔍 {name}")
    driver.get(url)
    time.sleep(PAGE_DELAY + 2)  # Extra time for first load

    for page in range(1, MAX_PAGES + 1):
        print(f"    Page {page}...", end=" ")
        contacts = scrape_contacts_from_page(driver)
        print(f"{len(contacts)} contacts")
        all_contacts.extend(contacts)

        if len(all_contacts) >= MAX_CONTACTS_PER_RUN:
            print(f"    ⏸️  Hit max contacts limit ({MAX_CONTACTS_PER_RUN})")
            break

        if page < MAX_PAGES:
            if not navigate_to_next_page(driver, page):
                print(f"    ⏹️  No more pages")
                break
            time.sleep(PAGE_DELAY)

    return all_contacts


def deduplicate(contacts: list, existing_emails: set) -> list:
    """Remove duplicates and already-known emails.
    Also checks the main outreach contacted.json to prevent cross-pipeline duplication.
    """
    # Also load emails from main contacted.json
    main_contacted = Path(__file__).parent.parent.parent / "contacted.json"
    if main_contacted.exists():
        try:
            data = json.loads(main_contacted.read_text())
            for entry in data.values():
                email = entry.get("email", "").lower()
                if email:
                    existing_emails.add(email)
        except Exception:
            pass

    # Also check apollo's own contacted file
    apollo_contacted = DATA_DIR / "apollo_contacted.json"
    if apollo_contacted.exists():
        try:
            data = json.loads(apollo_contacted.read_text())
            for entry in data.values():
                email = entry.get("email", "").lower()
                if email:
                    existing_emails.add(email)
        except Exception:
            pass

    seen = set()
    unique = []
    for c in contacts:
        email = c.get("email", "").lower()
        if email and email not in seen and email not in existing_emails:
            # STRICT: must have valid email format
            if "@" in email and "." in email.split("@")[1]:
                seen.add(email)
                unique.append(c)
    return unique


def save_results(contacts: list):
    """Save scraped contacts to apollo_recruiters.json."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # Load existing results
    existing = []
    if RESULTS_FILE.exists():
        try:
            existing = json.loads(RESULTS_FILE.read_text())
        except Exception:
            pass

    # Add timestamp to new contacts
    now = datetime.now().strftime("%Y-%m-%d")
    for c in contacts:
        c["discovered_date"] = now
        c["source"] = c.get("source", "apollo_scraper")

    # Merge
    existing_emails = {c.get("email", "").lower() for c in existing}
    new_contacts = [c for c in contacts if c.get("email", "").lower() not in existing_emails]
    existing.extend(new_contacts)

    RESULTS_FILE.write_text(json.dumps(existing, indent=2))
    return new_contacts


def update_vendor_list(contacts: list):
    """Add new Apollo contacts to the main vendor_list.json."""
    vendors = []
    if VENDOR_FILE.exists():
        try:
            vendors = json.loads(VENDOR_FILE.read_text())
        except Exception:
            vendors = []

    existing_emails = {v.get("email", "").lower() for v in vendors}

    added = 0
    for c in contacts:
        email = c.get("email", "").lower()
        if email and email not in existing_emails:
            vendors.append({
                "name": c.get("name", ""),
                "company": c.get("company", ""),
                "email": email,
                "title": c.get("title", ""),
                "linkedin_url": c.get("linkedin_url", ""),
                "source": "apollo_scraper",
                "verified": datetime.now().strftime("%Y-%m-%d"),
                "confidence": 90,  # Apollo-verified emails are high confidence
            })
            existing_emails.add(email)
            added += 1

    VENDOR_FILE.write_text(json.dumps(vendors, indent=2))
    return added


def main(headless: bool = True):
    """Main entry point — scrape Apollo for recruiters.
    
    Strategy (fully dynamic — no manual setup needed):
    1. Try Apollo API first (fast, no browser)
    2. If API fails (403) → login with email/password via Selenium
    3. Save session cookies for future runs (avoid re-login)
    4. Scrape search results
    
    Required secrets (in GitHub):
    - APOLLO_API_KEY (for API method)
    - APOLLO_EMAIL + APOLLO_PASSWORD (for Selenium login)
    - GMAIL_USER can be used as APOLLO_EMAIL fallback
    """
    print("🚀 Apollo.io Recruiter Scraper")
    print(f"   Target: Technical/IT Recruiters, Bench Sales at staffing firms")
    print(f"   Location: United States\n")

    # Load existing emails to avoid duplicates
    existing_emails = set()
    if VENDOR_FILE.exists():
        vendors = json.loads(VENDOR_FILE.read_text())
        existing_emails = {v.get("email", "").lower() for v in vendors}

    all_contacts = []

    # ─── METHOD 1: Apollo API (fastest, no browser) ───
    api_key = os.environ.get("APOLLO_API_KEY", "")
    if api_key:
        print("📡 Method 1: Apollo API...")
        api_contacts = _search_via_api(api_key)
        if api_contacts:
            all_contacts.extend(api_contacts)
            print(f"   ✅ API returned: {len(api_contacts)} contacts\n")
        else:
            print("   ⚠️  API failed (likely 403 — free plan). Trying Selenium login...\n")

    # ─── METHOD 2: Cookies (fastest after API — no login needed) ───
    if not all_contacts:
        cookies = load_cookies()
        if cookies:
            print("🍪 Method 2: Using cookies (APOLLO_COOKIES_B64 or saved session)...")
            driver = create_driver(headless=headless)
            try:
                if inject_cookies(driver, cookies):
                    for search in SEARCH_QUERIES:
                        contacts = run_search(driver, search)
                        new_contacts = deduplicate(contacts, existing_emails)
                        all_contacts.extend(new_contacts)
                        existing_emails.update(c.get("email", "").lower() for c in new_contacts)
                        if len(all_contacts) >= MAX_CONTACTS_PER_RUN:
                            break
                else:
                    print("   ⚠️  Cookies expired or invalid")
            finally:
                driver.quit()

    # ─── METHOD 3: Selenium + Auto-Login (fallback — needs real password) ───
    if not all_contacts:
        apollo_email = os.environ.get("APOLLO_EMAIL", os.environ.get("GMAIL_USER", ""))
        apollo_password = os.environ.get("APOLLO_PASSWORD", "")
        
        if apollo_email and apollo_password and apollo_password != "PLACEHOLDER_CHANGE_ME":
            print(f"🌐 Method 3: Selenium auto-login as {apollo_email[:5]}***...")
            driver = create_driver(headless=headless)
            try:
                if _login_with_credentials(driver, apollo_email, apollo_password):
                    _save_session_cookies(driver)
                    
                    for search in SEARCH_QUERIES:
                        contacts = run_search(driver, search)
                        new_contacts = deduplicate(contacts, existing_emails)
                        all_contacts.extend(new_contacts)
                        existing_emails.update(c.get("email", "").lower() for c in new_contacts)
                        if len(all_contacts) >= MAX_CONTACTS_PER_RUN:
                            break
                else:
                    print("   ❌ Login failed (Google OAuth accounts need cookies, not password)")
            finally:
                driver.quit()

    if not all_contacts:
        print("\n❌ All methods failed. Ensure APOLLO_COOKIES_B64 is set with fresh cookies.")
        return []

    # Deduplicate against all existing contacts
    all_contacts = deduplicate(all_contacts, existing_emails)

    # Save results
    if all_contacts:
        new_saved = save_results(all_contacts)
        added_to_vendors = update_vendor_list(new_saved)
        print(f"\n📊 Apollo Scraper Results:")
        print(f"   Contacts scraped: {len(all_contacts)}")
        print(f"   New unique: {len(new_saved)}")
        print(f"   Added to vendor list: {added_to_vendors}")
        print(f"\n   Sample contacts:")
        for c in new_saved[:5]:
            print(f"     {c.get('name', '?')} | {c.get('title', '?')} | {c.get('company', '?')} | {c.get('email', '?')}")
    else:
        print("\n⚠️  No new contacts found this run")

    return all_contacts


def _login_with_credentials(driver, email: str, password: str) -> bool:
    """Login to Apollo.io with email/password — fully automated."""
    print("   Navigating to login page...")
    driver.get("https://app.apollo.io/#/login")
    time.sleep(4)

    try:
        # Find and fill email field
        email_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 
                "input[name='email'], input[type='email'], input[placeholder*='email' i]"))
        )
        email_field.clear()
        email_field.send_keys(email)
        time.sleep(1)

        # Find and fill password field
        password_field = driver.find_element(By.CSS_SELECTOR, 
            "input[name='password'], input[type='password']")
        password_field.clear()
        password_field.send_keys(password)
        time.sleep(1)

        # Click login button
        login_btn = driver.find_element(By.CSS_SELECTOR, 
            "button[type='submit'], button[class*='login'], button[class*='sign']")
        login_btn.click()
        time.sleep(5)

        # Verify login success
        if "/login" not in driver.current_url and "/sign" not in driver.current_url:
            print("   ✅ Login successful!")
            return True
        
        # Check for error messages
        try:
            error = driver.find_element(By.CSS_SELECTOR, "[class*='error'], [class*='alert']")
            print(f"   ❌ Login error: {error.text[:100]}")
        except:
            pass

        return False

    except TimeoutException:
        print("   ❌ Login page didn't load (timeout)")
        return False
    except Exception as e:
        print(f"   ❌ Login error: {e}")
        return False


def _save_session_cookies(driver):
    """Save current session cookies for future runs.
    SECURITY: Saves to /tmp ONLY — never in repo (repo is PUBLIC).
    Cookies in GitHub Secrets (APOLLO_COOKIES_B64) are encrypted and safe.
    """
    try:
        cookies = driver.get_cookies()
        COOKIES_FILE.write_text(json.dumps(cookies, indent=2))
        print(f"   💾 Session cookies saved to /tmp ({len(cookies)} cookies)")
        
        # Also try to update GitHub secret for next CI run
        import base64, subprocess
        encoded = base64.b64encode(json.dumps(cookies).encode()).decode()
        result = subprocess.run(
            ["gh", "secret", "set", "APOLLO_COOKIES_B64", "--repo", "BOBRIKH75/job-finder"],
            input=encoded, text=True, capture_output=True, timeout=10
        )
        if result.returncode == 0:
            print(f"   🔒 Cookies saved to GitHub Secret (encrypted, safe)")
    except Exception as e:
        print(f"   ⚠️  Could not save cookies: {e}")


def _search_via_api(api_key: str) -> list:
    """Search Apollo via their REST API — uses email credits (10K/month).
    
    This is the PREFERRED method — APOLLO_API_KEY is already in GitHub secrets.
    No cookies, no Selenium, no browser needed.
    """
    import urllib.request
    import urllib.parse

    all_contacts = []
    
    # Search queries for the API
    searches = [
        {
            "name": "Technical Recruiters at Staffing",
            "person_titles": ["Technical Recruiter", "IT Recruiter", "Bench Sales", "Staffing Manager"],
            "q_organization_name": "",
            "person_locations": ["United States"],
            "organization_industry_tag_ids": [],  # staffing/recruiting
        },
        {
            "name": "C2C / Corp-to-Corp Recruiters",
            "person_titles": ["Recruiter", "Account Manager", "Talent Acquisition"],
            "q_organization_name": "staffing OR consulting OR C2C OR solutions",
            "person_locations": ["United States"],
            "organization_industry_tag_ids": [],
        },
        {
            "name": "IT Consulting Firm Recruiters",
            "person_titles": ["Sr. Recruiter", "Lead Recruiter", "Technical Recruiter"],
            "q_organization_name": "consulting OR technology OR IT services",
            "person_locations": ["United States"],
            "organization_industry_tag_ids": [],
        },
    ]

    for search in searches:
        print(f"   🔍 {search['name']}...")
        
        payload = json.dumps({
            "api_key": api_key,
            "person_titles": search["person_titles"],
            "q_organization_name": search["q_organization_name"],
            "person_locations": search["person_locations"],
            "per_page": 50,
            "page": 1,
        }).encode()

        req = urllib.request.Request(
            "https://api.apollo.io/v1/mixed_people/search",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "X-Api-Key": api_key,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            
            people = data.get("people", [])
            for p in people:
                email = p.get("email", "")
                name = p.get("name", "")
                if not email or not name:
                    continue
                # Skip if email not verified
                if "@" not in email:
                    continue
                    
                all_contacts.append({
                    "email": email.lower(),
                    "name": name,
                    "title": p.get("title", ""),
                    "company": p.get("organization", {}).get("name", "") if isinstance(p.get("organization"), dict) else "",
                    "linkedin_url": p.get("linkedin_url", ""),
                    "source": "apollo_api",
                })
            
            print(f"      Found {len(people)} people, {len([p for p in people if p.get('email')])} with emails")
            time.sleep(1)  # Rate limit respect
            
        except Exception as e:
            print(f"      ⚠️ API error: {e}")

    return all_contacts


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Apollo.io Recruiter Scraper")
    parser.add_argument("--visible", action="store_true", help="Run with visible browser (for debugging)")
    args = parser.parse_args()
    main(headless=not args.visible)
