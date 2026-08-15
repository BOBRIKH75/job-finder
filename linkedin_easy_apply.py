"""LinkedIn Easy Apply Bot — SAFE MODE (cookie-based auth).

Uses LinkedIn session cookies instead of email/password login.
This is safer because:
- No login event from a new IP (GitHub Actions IPs change every run)
- Avoids Google OAuth popup (account uses Google SSO)
- Cookies last ~1 year; password login triggers "new device" alerts

Setup (one-time, run locally):
  1. Log in to LinkedIn in Chrome
  2. DevTools → Application → Cookies → www.linkedin.com
  3. Copy values for: li_at, JSESSIONID, liap
  4. Run: python extract_li_cookies.py  (or encode manually — see README)
  5. Set GitHub Secret: LINKEDIN_COOKIES = base64(JSON array of cookie dicts)

SAFETY RULES:
1. NEVER exceed 15 apps per session (30/day max — LinkedIn limit is 50)
2. ALWAYS random delays 30-90s between applications
3. ALWAYS check for restriction warnings before each apply
4. NEVER apply to the same job twice
"""
import base64, json, os, random, time
from pathlib import Path
from datetime import datetime

# STRICT SAFETY LIMITS — DO NOT INCREASE
MAX_APPLICATIONS_PER_RUN = 15  # 2 runs/day × 15 = 30/day (LinkedIn limit is 50)
MIN_DELAY_SECONDS = 30  # minimum wait between applications
MAX_DELAY_SECONDS = 90  # maximum wait between applications
SEARCH_KEYWORDS = [
    "Java Developer contract remote",
    "Java Spring Boot developer C2C",
    "Senior Java Backend Engineer contract",
]

APPLIED_FILE = "linkedin_applied.json"


def load_applied():
    if os.path.exists(APPLIED_FILE):
        return json.loads(Path(APPLIED_FILE).read_text())
    return {"applied_ids": [], "total": 0, "last_run": None}


def save_applied(data):
    data["last_run"] = datetime.now().isoformat()
    Path(APPLIED_FILE).write_text(json.dumps(data, indent=2))


def human_delay():
    """Random delay to look human — 30 to 90 seconds."""
    delay = random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
    print(f"    ⏳ Waiting {delay:.0f}s (human simulation)...")
    time.sleep(delay)


def check_for_restrictions(driver) -> bool:
    """Check if LinkedIn is showing any warning/restriction."""
    try:
        page_text = driver.page_source.lower()
        danger_signals = [
            "unusual activity",
            "restricted",
            "verify your identity",
            "security verification",
            "we've limited",
            "temporarily restricted",
            "complete a captcha",
        ]
        for signal in danger_signals:
            if signal in page_text:
                print(f"    🚨 RESTRICTION DETECTED: '{signal}' — STOPPING IMMEDIATELY")
                return True
    except Exception:
        pass
    return False


def load_linkedin_cookies() -> list[dict]:
    """Load LinkedIn session cookies from LINKEDIN_COOKIES env var (base64 JSON)."""
    encoded = os.environ.get("LINKEDIN_COOKIES", "")
    if not encoded:
        return []
    try:
        return json.loads(base64.b64decode(encoded).decode())
    except Exception as e:
        print(f"  ⚠️  Could not decode LINKEDIN_COOKIES: {e}")
        return []


def alert_cookie_expired():
    """Send an email alert when LinkedIn cookies need refreshing."""
    resend_key = os.environ.get("RESEND_KEY", "")
    gmail_user = os.environ.get("GMAIL_USER", "bobrikh75@gmail.com")
    if not resend_key:
        print("  ⚠️  LINKEDIN_COOKIES expired — update the LINKEDIN_COOKIES secret")
        return
    import urllib.request
    payload = json.dumps({
        "from": "Job Agent <onboarding@resend.dev>",
        "to": [gmail_user],
        "subject": "ACTION REQUIRED: LinkedIn cookies expired",
        "text": (
            "Your LinkedIn session cookies have expired.\n\n"
            "To fix:\n"
            "1. Log in to LinkedIn in Chrome\n"
            "2. DevTools → Application → Cookies → www.linkedin.com\n"
            "3. Copy li_at, JSESSIONID, liap values\n"
            "4. Run extract_li_cookies.py locally\n"
            "5. Update GitHub Secret: LINKEDIN_COOKIES\n\n"
            "The LinkedIn Easy Apply bot will resume automatically on the next run."
        ),
    }).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        print("  📧 Alert email sent — check your inbox to refresh LinkedIn cookies")
    except Exception:
        print("  ⚠️  LinkedIn cookies expired — update LINKEDIN_COOKIES secret")


def inject_cookies(driver, cookies: list[dict]):
    """Inject LinkedIn cookies into the browser session."""
    # Must be on the domain before setting cookies
    driver.get("https://www.linkedin.com")
    time.sleep(2)
    for cookie in cookies:
        try:
            # Selenium requires domain without leading dot for some cookies
            c = {k: v for k, v in cookie.items() if k in ("name", "value", "domain", "path", "secure", "httpOnly")}
            driver.add_cookie(c)
        except Exception as e:
            print(f"    ⚠️  Could not inject cookie {cookie.get('name')}: {e}")


def main():
    cookies = load_linkedin_cookies()

    if not cookies:
        print("❌ LINKEDIN_COOKIES secret not set")
        print("   This bot uses cookie auth (no password needed — works with Google SSO)")
        print("   See the docstring at the top of this file for setup instructions")
        return

    applied_data = load_applied()

    # Safety: don't run more than twice per day
    if applied_data.get("last_run"):
        from datetime import timedelta
        last = datetime.fromisoformat(applied_data["last_run"])
        if datetime.now() - last < timedelta(hours=5):
            print(f"⏸️ Last run was {last.isoformat()} — too recent, skipping")
            return

    print(f"🔗 LinkedIn Easy Apply Bot — SAFE MODE (cookie auth)")
    print(f"   Max applications: {MAX_APPLICATIONS_PER_RUN}")
    print(f"   Delay between: {MIN_DELAY_SECONDS}-{MAX_DELAY_SECONDS}s")
    print(f"   Previously applied: {applied_data['total']}")
    print()

    try:
        import undetected_chromedriver as uc
        options = uc.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        driver = uc.Chrome(options=options)
    except Exception as e:
        print(f"❌ Browser launch failed: {e}")
        return

    applied_count = 0

    try:
        # Inject cookies instead of logging in
        print("  🍪 Injecting LinkedIn session cookies...")
        inject_cookies(driver, cookies)

        # Navigate to feed to verify session is valid
        driver.get("https://www.linkedin.com/feed/")
        time.sleep(4)

        current = driver.current_url
        if "login" in current or "authwall" in current or "checkpoint" in current:
            print("  🚨 LinkedIn cookies expired or invalid — session not authenticated")
            alert_cookie_expired()
            driver.quit()
            return

        print(f"  ✅ Session valid — at {current[:60]}")

        if check_for_restrictions(driver):
            driver.quit()
            return

        time.sleep(random.uniform(3, 6))  # brief pause before searching

        # Search for jobs
        for keyword in SEARCH_KEYWORDS:
            if applied_count >= MAX_APPLICATIONS_PER_RUN:
                break

            print(f"\n  🔍 Searching: '{keyword}'")
            search_url = f"https://www.linkedin.com/jobs/search/?keywords={keyword.replace(' ', '%20')}&f_AL=true&f_WT=2"
            driver.get(search_url)
            time.sleep(5)

            if check_for_restrictions(driver):
                break

            # Find job cards
            try:
                job_cards = driver.find_elements("css selector", ".job-card-container")
                print(f"    Found {len(job_cards)} jobs")

                for card in job_cards[:5]:  # max 5 per search keyword
                    if applied_count >= MAX_APPLICATIONS_PER_RUN:
                        break

                    try:
                        # Click the job to open details
                        card.click()
                        time.sleep(3)

                        # Get job ID to check if already applied
                        job_id = card.get_attribute("data-job-id") or card.get_attribute("data-occludable-job-id") or ""
                        if job_id in applied_data["applied_ids"]:
                            print(f"    ⏭️ Already applied to {job_id}")
                            continue

                        # Check for Easy Apply button
                        try:
                            easy_apply_btn = driver.find_element("css selector", ".jobs-apply-button, button.jobs-apply-button")
                            btn_text = easy_apply_btn.text.lower()
                            if "easy apply" not in btn_text:
                                print(f"    ⏭️ Not Easy Apply")
                                continue
                        except Exception:
                            print(f"    ⏭️ No Easy Apply button")
                            continue

                        # Click Easy Apply
                        print(f"    📝 Applying (job {job_id})...")
                        easy_apply_btn.click()
                        time.sleep(3)

                        if check_for_restrictions(driver):
                            break

                        # Handle the application modal
                        # Most Easy Apply is 1-click with pre-filled profile
                        submitted = False
                        for step in range(5):  # max 5 steps
                            try:
                                # Look for Submit button
                                submit_btn = driver.find_element("css selector", "button[aria-label*='Submit'], button:has-text('Submit application')")
                                submit_btn.click()
                                time.sleep(3)
                                submitted = True
                                break
                            except Exception:
                                pass

                            try:
                                # Look for Next/Review button
                                next_btn = driver.find_element("css selector", "button[aria-label*='Continue'], button[aria-label*='Next'], button[aria-label*='Review']")
                                next_btn.click()
                                time.sleep(2)
                            except Exception:
                                # Try dismiss if stuck
                                try:
                                    driver.find_element("css selector", "button[aria-label='Dismiss']").click()
                                except Exception:
                                    pass
                                break

                        if submitted:
                            applied_count += 1
                            applied_data["applied_ids"].append(job_id)
                            applied_data["total"] += 1
                            print(f"    ✅ Applied! ({applied_count}/{MAX_APPLICATIONS_PER_RUN})")

                            # Dismiss the post-apply modal
                            try:
                                driver.find_element("css selector", "button[aria-label='Dismiss']").click()
                            except Exception:
                                pass
                        else:
                            print(f"    ⚠️ Could not complete application")
                            # Close the modal
                            try:
                                driver.find_element("css selector", "button[aria-label='Dismiss']").click()
                                time.sleep(1)
                                driver.find_element("css selector", "button[data-test-modal-close-btn]").click()
                            except Exception:
                                pass

                        # CRITICAL: Human-like delay between applications
                        human_delay()

                    except Exception as e:
                        print(f"    ⚠️ Error on job: {str(e)[:50]}")
                        continue

            except Exception as e:
                print(f"    ⚠️ Search error: {str(e)[:50]}")
                continue

    except Exception as e:
        print(f"❌ Fatal error: {e}")

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    # Save results
    save_applied(applied_data)
    print(f"\n📊 Results: {applied_count} new applications | {applied_data['total']} total all-time")


if __name__ == "__main__":
    main()
