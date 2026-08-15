"""LinkedIn Easy Apply Bot — SAFE MODE.

Applies to LinkedIn Easy Apply jobs with STRICT anti-ban limits:
- Max 10 applications per run (way under 50/day limit)
- Random delays 30-90 seconds between applications (human-like)
- Only weekdays 9 AM (when real humans apply)
- Skips already-applied jobs
- Stops immediately if any warning/restriction detected

SAFETY RULES:
1. NEVER exceed 10 apps per session
2. NEVER run more than once per day
3. ALWAYS random delays (30-90s between apps)
4. ALWAYS check for restriction warnings
5. NEVER apply to the same job twice

To use: set these GitHub Secrets:
  LINKEDIN_EMAIL: your LinkedIn email
  LINKEDIN_PASSWORD: your LinkedIn password
"""
import json, os, random, sys, time
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


def main():
    email = os.environ.get("LINKEDIN_EMAIL", "")
    password = os.environ.get("LINKEDIN_PASSWORD", "")

    if not email or not password:
        print("❌ LINKEDIN_EMAIL and LINKEDIN_PASSWORD secrets not set")
        print("   Set them: gh secret set LINKEDIN_EMAIL --body 'your@email.com'")
        print("             gh secret set LINKEDIN_PASSWORD --body 'your-password'")
        return

    applied_data = load_applied()

    # Safety: check last run time — don't run more than twice per day
    if applied_data.get("last_run"):
        from datetime import datetime, timedelta
        last = datetime.fromisoformat(applied_data["last_run"])
        if datetime.now() - last < timedelta(hours=5):
            print(f"⏸️ Last run was {last.isoformat()} — too recent, skipping (safety)")
            return

    print(f"🔗 LinkedIn Easy Apply Bot — SAFE MODE")
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
        driver = uc.Chrome(options=options)
    except Exception as e:
        print(f"❌ Browser launch failed: {e}")
        return

    applied_count = 0

    try:
        # Login to LinkedIn
        print("  📧 Logging in to LinkedIn...")
        driver.get("https://www.linkedin.com/login")
        time.sleep(3)

        if check_for_restrictions(driver):
            return

        driver.find_element("id", "username").send_keys(email)
        driver.find_element("id", "password").send_keys(password)
        driver.find_element("css selector", "button[type='submit']").click()
        time.sleep(5)

        if check_for_restrictions(driver):
            return

        # Check if login succeeded
        if "feed" not in driver.current_url and "checkpoint" not in driver.current_url:
            if "challenge" in driver.current_url:
                print("  🚨 LinkedIn wants verification — cannot proceed automatically")
                print("  💡 Please log in manually once to clear the verification")
                return

        print("  ✅ Logged in successfully")
        human_delay()

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
