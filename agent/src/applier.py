"""Browser applier — actually opens pages, fills forms, clicks Submit, learns from failures."""
import json, os, re, time, random
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

PROFILE_PATH = Path(__file__).parent.parent / "config" / "profile.json"
RESUME_PATH = Path(__file__).parent.parent / "resume.pdf"
SCREENSHOTS = Path(__file__).parent.parent / "screenshots"
LEARNED_FILE = Path(__file__).parent.parent / "data" / "learned_selectors.json"

# Field patterns — maps label keywords to profile keys
FIELD_MAP = {
    "name": "name", "full name": "name",
    "first name": "first_name", "last name": "last_name",
    "email": "email", "e-mail": "email",
    "phone": "phone", "mobile": "phone", "telephone": "phone",
    "city": "city", "location": "location",
    "state": "state", "zip": "zip", "country": "country",
    "linkedin": "linkedin", "github": "github",
    "company": "company", "current company": "company", "organization": "company",
}

# Known ATS selectors (learned + hardcoded)
LEVER_SELECTORS = {
    "name": 'input[name="name"]',
    "email": 'input[name="email"]',
    "phone": 'input[name="phone"]',
    "company": 'input[name="org"]',
    "linkedin": 'input[name="urls[LinkedIn]"]',
    "github": 'input[name="urls[GitHub]"]',
    "resume": 'input[type="file"]',
    "submit": 'button:has-text("Submit application")',
}

# Answers for common questions
KNOWN_ANSWERS = {
    "authorized to work": "Yes",
    "sponsorship": "No",
    "willing to relocate": "No",
    "start date": "Immediately",
    "salary": "$55-90/hr C2C",
    "hear about": "Online Job Board",
    "gender": "Decline",
    "race": "Decline",
    "veteran": "I am not",
    "disability": "I do not wish",
}


def load_profile() -> dict:
    p = json.loads(PROFILE_PATH.read_text())
    p["company"] = ""  # current company — leave blank for C2C
    p["location"] = f"{p['city']}, {p['state']}"
    return p


def load_learned() -> dict:
    if LEARNED_FILE.exists():
        return json.loads(LEARNED_FILE.read_text())
    return {"successes": {}, "failures": {}, "selectors": {}}


def save_learned(data: dict):
    LEARNED_FILE.parent.mkdir(parents=True, exist_ok=True)
    LEARNED_FILE.write_text(json.dumps(data, indent=2))


def screenshot(page, name: str) -> str:
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOTS / f"{int(time.time())}_{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path)


def human_delay(min_s=0.5, max_s=1.5):
    time.sleep(random.uniform(min_s, max_s))


def fill_field(page, selector: str, value: str, label: str = "") -> bool:
    """Try to fill a field. Returns True if successful."""
    try:
        el = page.locator(selector)
        if el.count() > 0 and el.first.is_visible(timeout=2000):
            el.first.fill(value)
            human_delay(0.3, 0.8)
            return True
    except Exception:
        pass
    return False


def try_answer_question(page, label_text: str) -> bool:
    """Try to answer a known question by matching label text."""
    lower = label_text.lower()
    for pattern, answer in KNOWN_ANSWERS.items():
        if pattern in lower:
            # Try radio buttons first
            for opt in page.locator(f'label:has-text("{answer}")').all():
                try:
                    opt.click()
                    return True
                except Exception:
                    pass
            # Try select dropdown
            for sel in page.locator("select").all():
                try:
                    options = [o.inner_text() for o in sel.locator("option").all()]
                    for o in options:
                        if answer.lower() in o.lower():
                            sel.select_option(label=o)
                            return True
                except Exception:
                    pass
    return False


def detect_form_fields(page) -> list[dict]:
    """Detect all visible form fields on the page."""
    fields = page.evaluate("""() => {
        const results = [];
        for (const el of document.querySelectorAll('input:not([type=hidden]), select, textarea')) {
            const rect = el.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) continue;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            const label = el.closest('label')?.innerText
                || document.querySelector(`label[for="${el.id}"]`)?.innerText
                || el.getAttribute('aria-label')
                || el.getAttribute('placeholder')
                || el.getAttribute('name')
                || '';
            results.push({
                tag: el.tagName.toLowerCase(),
                type: el.type || '',
                name: el.name || '',
                id: el.id || '',
                label: label.trim().substring(0, 100),
                selector: el.id ? '#' + el.id : (el.name ? `[name="${el.name}"]` : ''),
            });
        }
        return results;
    }""")
    return fields


def apply_to_lever(page, profile: dict, job_url: str, dry_run: bool = False) -> dict:
    """Fill and submit a Lever application form."""
    result = {"url": job_url, "status": "pending", "fields_filled": 0, "errors": []}

    apply_url = job_url.rstrip("/")
    if not apply_url.endswith("/apply"):
        apply_url += "/apply"

    page.goto(apply_url, wait_until="networkidle", timeout=30000)
    human_delay(1, 2)

    # Check page loaded
    if page.locator("text=Page not found").count() > 0:
        result["status"] = "not_found"
        return result

    screenshot(page, "01_loaded")

    # Upload resume
    file_input = page.locator('input[type="file"]')
    if file_input.count() > 0 and RESUME_PATH.exists():
        file_input.first.set_input_files(str(RESUME_PATH))
        result["fields_filled"] += 1
        human_delay(1, 2)

    # Fill standard Lever fields
    for field_key, selector in LEVER_SELECTORS.items():
        if field_key in ("resume", "submit"):
            continue
        value = profile.get(field_key, "")
        if value and fill_field(page, selector, value, field_key):
            result["fields_filled"] += 1

    screenshot(page, "02_filled")

    # Handle any visible questions (radio/select)
    for label_el in page.locator("label").all():
        try:
            text = label_el.inner_text(timeout=1000)
            if text:
                try_answer_question(page, text)
        except Exception:
            pass

    screenshot(page, "03_before_submit")

    if dry_run:
        result["status"] = "dry_run"
        return result

    # Submit
    submit = page.locator(LEVER_SELECTORS["submit"])
    if submit.count() > 0:
        submit.first.click()
        human_delay(2, 4)
        try:
            page.wait_for_url("**/thanks**", timeout=15000)
            result["status"] = "submitted"
            screenshot(page, "04_success")
        except PwTimeout:
            result["status"] = "submit_failed"
            result["errors"].append("No redirect to /thanks")
            screenshot(page, "04_failed")
    else:
        result["status"] = "no_submit_button"

    return result


def apply_generic(page, profile: dict, job_url: str, dry_run: bool = False) -> dict:
    """Try to fill any job application form using field detection."""
    result = {"url": job_url, "status": "pending", "fields_filled": 0, "errors": []}

    page.goto(job_url, wait_until="networkidle", timeout=30000)
    human_delay(1, 2)
    screenshot(page, "01_loaded")

    # Detect all form fields
    fields = detect_form_fields(page)

    for field in fields:
        label = field["label"].lower()
        selector = field["selector"]
        if not selector:
            continue

        # File upload
        if field["type"] == "file" and RESUME_PATH.exists():
            try:
                page.locator(selector).set_input_files(str(RESUME_PATH))
                result["fields_filled"] += 1
                continue
            except Exception:
                pass

        # Match label to profile
        for pattern, profile_key in FIELD_MAP.items():
            if pattern in label:
                value = profile.get(profile_key, "")
                if value and fill_field(page, selector, value, pattern):
                    result["fields_filled"] += 1
                break

        # Try known answers for questions
        if field["tag"] in ("select",) or field["type"] in ("radio", "checkbox"):
            try_answer_question(page, field["label"])

    screenshot(page, "02_filled")

    if dry_run:
        result["status"] = "dry_run"
        return result

    # Find and click submit
    for btn_text in ["Submit", "Apply", "Send Application", "Submit Application"]:
        btn = page.locator(f'button:has-text("{btn_text}")')
        if btn.count() > 0:
            btn.first.click()
            human_delay(2, 4)
            screenshot(page, "03_submitted")
            result["status"] = "submitted"
            return result

    result["status"] = "no_submit_button"
    return result


def run_applications(jobs: list[dict], dry_run: bool = True, max_apps: int = 10) -> list[dict]:
    """Main entry: apply to a list of jobs. Learns from each attempt."""
    profile = load_profile()
    learned = load_learned()
    results = []

    try:
        from playwright_stealth import Stealth
        pw_context = Stealth().use_sync(sync_playwright())
    except ImportError:
        pw_context = sync_playwright()

    with pw_context as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/Denver",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        applied = 0
        for job in jobs:
            if applied >= max_apps:
                break

            url = job.get("url", "")
            ats = job.get("ats_type", "unknown")

            print(f"\n{'='*50}")
            print(f"Applying: {job.get('title', '?')} @ {job.get('company', '?')}")
            print(f"URL: {url} | ATS: {ats}")

            try:
                if "lever.co" in url:
                    result = apply_to_lever(page, profile, url, dry_run)
                else:
                    result = apply_generic(page, profile, url, dry_run)

                result["title"] = job.get("title", "")
                result["company"] = job.get("company", "")
                results.append(result)

                # Learn from result
                domain = re.sub(r'https?://(www\.)?', '', url).split('/')[0]
                if result["status"] == "submitted":
                    learned["successes"][domain] = learned["successes"].get(domain, 0) + 1
                    applied += 1
                    print(f"  ✅ SUBMITTED — {result['fields_filled']} fields filled")
                elif result["status"] == "dry_run":
                    applied += 1
                    print(f"  🔒 DRY RUN — {result['fields_filled']} fields filled")
                else:
                    learned["failures"][domain] = learned["failures"].get(domain, 0) + 1
                    print(f"  ❌ {result['status']} — {result.get('errors', [])}")

            except Exception as e:
                print(f"  ❌ Exception: {e}")
                screenshot(page, "exception")
                results.append({"url": url, "status": "error", "error": str(e)})

            human_delay(3, 6)  # delay between applications

        browser.close()

    save_learned(learned)

    # Summary
    submitted = sum(1 for r in results if r["status"] in ("submitted", "dry_run"))
    failed = sum(1 for r in results if r["status"] not in ("submitted", "dry_run"))
    print(f"\n📊 Results: {submitted} applied, {failed} failed out of {len(results)} attempted")

    return results
