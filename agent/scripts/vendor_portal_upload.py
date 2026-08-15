#!/usr/bin/env python3
"""
Upload Bob Rikh's resume to staffing firm candidate portals.

Each firm has a different submission flow. This script handles the top firms
that allow direct resume submission without an account.

Run: python scripts/vendor_portal_upload.py
"""
import json, os, time, random
from pathlib import Path
from playwright.sync_api import sync_playwright

PROFILE = json.loads((Path(__file__).parent.parent / "config" / "profile.json").read_text())
RESUME_PATH = Path(__file__).parent.parent / "resume.pdf"
HISTORY_FILE = Path(__file__).parent.parent.parent / "data" / "portal_upload_history.json"

# Resume Google Drive link as fallback when file upload is blocked
RESUME_LINK = "https://drive.google.com/drive/folders/1sJRyHCTC2Xend6VWn6hM07VufWQdw_qV"
LINKEDIN_URL = "https://www.linkedin.com/in/bobrikh75/"

# Portals that accept direct resume submission — tested and automatable
# Format: {id, name, url, method}
PORTALS = [
    {
        "id": "dice",
        "name": "Dice.com",
        "url": "https://www.dice.com/dashboard/profile",
        "method": "profile_update",
        "note": "Update skills/availability on profile page",
    },
    {
        "id": "collabera",
        "name": "Collabera",
        "url": "https://www.collabera.com/submit_resume/",
        "method": "form_fill",
    },
    {
        "id": "mastech",
        "name": "Mastech Digital",
        "url": "https://www.mastechdigital.com/careers/submit-resume/",
        "method": "form_fill",
    },
    {
        "id": "tier2tek",
        "name": "Tier2Tek Staffing",
        "url": "https://tier2tek.com/job-seekers/",
        "method": "form_fill",
    },
    {
        "id": "kforce",
        "name": "Kforce",
        "url": "https://www.kforce.com/find-a-job/",
        "method": "form_fill",
    },
    {
        "id": "genesis10",
        "name": "Genesis10",
        "url": "https://www.genesis10.com/job-seeker/submit-your-resume/",
        "method": "form_fill",
    },
    {
        "id": "apexsystems",
        "name": "Apex Systems",
        "url": "https://www.apexsystems.com/job-seekers/submit-your-resume/",
        "method": "form_fill",
    },
]

PROFILE_ANSWERS = {
    "first": PROFILE.get("first_name", "Bob"),
    "last": PROFILE.get("last_name", "Rikh"),
    "email": PROFILE.get("email", "bobrikh75@gmail.com"),
    "phone": PROFILE.get("phone", "347-268-5917"),
    "city": PROFILE.get("city", "Parker"),
    "state": PROFILE.get("state", "CO"),
    "zip": PROFILE.get("zip", "80314"),
    "linkedin": PROFILE.get("linkedin", LINKEDIN_URL),
    "title": PROFILE.get("title", "Senior Java Backend Developer"),
    "experience": "10",
    "skills": "Java, Spring Boot, Microservices, Kafka, Kubernetes, Docker, AWS",
    "rate": "75",
    "availability": "Immediate",
    "authorization": "Green Card Holder — No Sponsorship Required",
}


def wait(a=0.5, b=1.5):
    time.sleep(random.uniform(a, b))


def load_history() -> dict:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return {}


def save_history(history: dict):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, indent=2))


def already_uploaded(history: dict, portal_id: str, days: int = 30) -> bool:
    from datetime import datetime, timedelta
    entry = history.get(portal_id)
    if not entry:
        return False
    last = datetime.fromisoformat(entry["last_uploaded"])
    return (datetime.utcnow() - last).days < days


def fill_generic_form(page, portal: dict) -> bool:
    """Fill a generic resume submission form using common field patterns."""
    from datetime import datetime

    label_map = {
        "first name": PROFILE_ANSWERS["first"],
        "given name": PROFILE_ANSWERS["first"],
        "last name": PROFILE_ANSWERS["last"],
        "surname": PROFILE_ANSWERS["last"],
        "email": PROFILE_ANSWERS["email"],
        "phone": PROFILE_ANSWERS["phone"],
        "mobile": PROFILE_ANSWERS["phone"],
        "city": PROFILE_ANSWERS["city"],
        "state": PROFILE_ANSWERS["state"],
        "zip": PROFILE_ANSWERS["zip"],
        "postal": PROFILE_ANSWERS["zip"],
        "linkedin": PROFILE_ANSWERS["linkedin"],
        "title": PROFILE_ANSWERS["title"],
        "position": PROFILE_ANSWERS["title"],
        "job title": PROFILE_ANSWERS["title"],
        "years": PROFILE_ANSWERS["experience"],
        "experience": PROFILE_ANSWERS["experience"],
        "rate": PROFILE_ANSWERS["rate"],
        "salary": "150000",
        "hourly": PROFILE_ANSWERS["rate"],
        "skill": PROFILE_ANSWERS["skills"],
        "availability": PROFILE_ANSWERS["availability"],
        "available": PROFILE_ANSWERS["availability"],
        "authorization": PROFILE_ANSWERS["authorization"],
        "work auth": PROFILE_ANSWERS["authorization"],
        "name": f"{PROFILE_ANSWERS['first']} {PROFILE_ANSWERS['last']}",
        "full name": f"{PROFILE_ANSWERS['first']} {PROFILE_ANSWERS['last']}",
    }

    filled = 0
    # Text inputs
    inputs = page.locator("input:not([type='hidden']):not([type='file']):not([type='submit']):not([type='checkbox']):not([type='radio'])").all()
    for inp in inputs:
        try:
            placeholder = (inp.get_attribute("placeholder") or "").lower()
            aria_label = (inp.get_attribute("aria-label") or "").lower()
            name_attr = (inp.get_attribute("name") or "").lower()
            combined = f"{placeholder} {aria_label} {name_attr}"
            for key, value in label_map.items():
                if key in combined:
                    inp.fill(str(value))
                    filled += 1
                    wait(0.1, 0.3)
                    break
        except Exception:
            pass

    # File upload
    if RESUME_PATH.exists():
        try:
            file_input = page.locator("input[type='file']").first
            file_input.set_input_files(str(RESUME_PATH))
            filled += 1
            wait(0.5, 1.0)
        except Exception:
            pass

    # Textareas (message/summary fields)
    textareas = page.locator("textarea").all()
    for ta in textareas:
        try:
            placeholder = (ta.get_attribute("placeholder") or "").lower()
            name_attr = (ta.get_attribute("name") or "").lower()
            if any(k in f"{placeholder} {name_attr}" for k in ["message", "summary", "cover", "note", "comment", "skill"]):
                ta.fill(
                    f"Senior Java Backend Developer with 10+ years experience. "
                    f"Spring Boot, Kafka, Kubernetes, AWS, Docker. "
                    f"Green Card holder, no sponsorship needed. Available immediately for C2C contract. "
                    f"Rate: $70-90/hr. Location: Parker CO, 100% remote preferred. "
                    f"LinkedIn: {LINKEDIN_URL}"
                )
                filled += 1
        except Exception:
            pass

    if filled == 0:
        print(f"    ⚠️  No fields filled for {portal['name']}")
        return False

    # Submit
    try:
        submit = page.locator("button[type='submit'], input[type='submit']").first
        submit.click()
        wait(2, 4)
        print(f"    ✅ Submitted to {portal['name']} ({filled} fields filled)")
        return True
    except Exception as e:
        print(f"    ❌ Submit failed for {portal['name']}: {e}")
        return False


def run_uploads():
    history = load_history()
    results = {"uploaded": [], "skipped": [], "failed": []}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        for portal in PORTALS:
            pid = portal["id"]

            if already_uploaded(history, pid, days=30):
                print(f"  ⏭️  Skipping {portal['name']} — uploaded within 30 days")
                results["skipped"].append(pid)
                continue

            print(f"  → {portal['name']}: {portal['url']}")
            try:
                page.goto(portal["url"], wait_until="domcontentloaded", timeout=20000)
                wait(1.5, 3.0)

                success = fill_generic_form(page, portal)

                if success:
                    history[pid] = {
                        "name": portal["name"],
                        "url": portal["url"],
                        "last_uploaded": __import__("datetime").datetime.utcnow().isoformat(),
                    }
                    results["uploaded"].append(pid)
                else:
                    results["failed"].append(pid)

            except Exception as e:
                print(f"    ❌ {portal['name']} error: {e}")
                results["failed"].append(pid)

            wait(3, 6)

        browser.close()

    save_history(history)
    print(f"\n📊 Portal Upload Results:")
    print(f"  Uploaded:  {len(results['uploaded'])} — {results['uploaded']}")
    print(f"  Skipped:   {len(results['skipped'])} (already done)")
    print(f"  Failed:    {len(results['failed'])} — {results['failed']}")
    return results


if __name__ == "__main__":
    run_uploads()
