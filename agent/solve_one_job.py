#!/usr/bin/env python3
"""Self-improving problem solver — picks ONE unsolved job, tries up to 5 approaches.

Uses Gemini AI as the "brain" to decide what strategy to try next based on
what failed before. Saves winning strategies so the main applier can use them.

Usage:
    python solve_one_job.py              # solve one job
    python solve_one_job.py --max-jobs 5 # solve up to 5 jobs in one run
"""
import argparse
import json
import os
import re
import time
import random
import traceback
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

# ─── Paths ───────────────────────────────────────────────────────────
BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
UNSOLVED_FILE = DATA_DIR / "unsolved_jobs.json"
STRATEGIES_FILE = DATA_DIR / "learned_strategies.json"
SOLVE_LOG_FILE = DATA_DIR / "solve_attempts.json"
PROFILE_PATH = BASE / "config" / "profile.json"
RESUME_PATH = BASE / "resume.pdf"
SCREENSHOTS_DIR = BASE / "screenshots"

MAX_ATTEMPTS = 5
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


# ─── Gemini AI Brain ─────────────────────────────────────────────────

def ask_gemini(prompt: str) -> str:
    """Ask Gemini for strategy advice. Returns text response."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return ""
    url = GEMINI_URL.format(model=GEMINI_MODEL) + f"?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1024},
    }
    try:
        resp = requests.post(url, json=payload, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        pass
    return ""


# ─── Data Loading ────────────────────────────────────────────────────

def load_unsolved() -> list[dict]:
    """Load unsolved jobs, sorted by date (newest first)."""
    if not UNSOLVED_FILE.exists():
        return []
    try:
        jobs = json.loads(UNSOLVED_FILE.read_text())
        # Deduplicate by URL
        seen = set()
        unique = []
        for j in jobs:
            url = j.get("url", "")
            if url and url not in seen:
                seen.add(url)
                unique.append(j)
        return unique
    except Exception:
        return []


def save_unsolved(jobs: list[dict]):
    """Save remaining unsolved jobs."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UNSOLVED_FILE.write_text(json.dumps(jobs[-200:], indent=2))


def load_strategies() -> dict:
    """Load learned strategies. Format: {domain: {strategy_key: details}}"""
    if not STRATEGIES_FILE.exists():
        return {}
    try:
        return json.loads(STRATEGIES_FILE.read_text())
    except Exception:
        return {}


def save_strategies(strategies: dict):
    """Save learned strategies."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STRATEGIES_FILE.write_text(json.dumps(strategies, indent=2))


def load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text())


def load_solve_log() -> list[dict]:
    if not SOLVE_LOG_FILE.exists():
        return []
    try:
        return json.loads(SOLVE_LOG_FILE.read_text())
    except Exception:
        return []


def save_solve_log(log: list[dict]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SOLVE_LOG_FILE.write_text(json.dumps(log[-500:], indent=2))


# ─── Strategy Generation ─────────────────────────────────────────────

STRATEGY_TEMPLATES = [
    {
        "name": "standard_fill",
        "description": "Standard: fill all visible fields, upload resume, click submit",
        "wait_before_fill": 2.0,
        "fill_order": "top_to_bottom",
        "click_submit_text": ["Submit", "Apply", "Submit Application"],
        "try_file_upload": True,
    },
    {
        "name": "slow_human",
        "description": "Slow human-like: longer waits, random pauses between fields",
        "wait_before_fill": 4.0,
        "fill_order": "top_to_bottom",
        "click_submit_text": ["Submit", "Apply", "Submit Application", "Send"],
        "try_file_upload": True,
        "inter_field_delay": 1.5,
    },
    {
        "name": "bottom_up_fill",
        "description": "Fill from bottom to top (some sites validate top fields immediately)",
        "wait_before_fill": 2.0,
        "fill_order": "bottom_to_top",
        "click_submit_text": ["Submit", "Apply", "Submit Application"],
        "try_file_upload": True,
    },
    {
        "name": "skip_optional",
        "description": "Only fill required fields, skip optional ones",
        "wait_before_fill": 2.0,
        "fill_order": "required_first",
        "click_submit_text": ["Submit", "Apply", "Submit Application"],
        "try_file_upload": True,
        "skip_optional": True,
    },
    {
        "name": "multi_page_aggressive",
        "description": "Click Next/Continue after each section, handle multi-page forms",
        "wait_before_fill": 3.0,
        "fill_order": "top_to_bottom",
        "click_submit_text": ["Next", "Continue", "Submit", "Apply"],
        "try_file_upload": True,
        "handle_multi_page": True,
    },
]


def get_next_strategy(attempt: int, domain: str, previous_errors: list[dict]) -> dict:
    """Get the next strategy to try. Uses Gemini if available, otherwise cycles templates."""
    # First, check if we have a learned strategy for this domain
    strategies = load_strategies()
    if domain in strategies and strategies[domain].get("winning_strategy"):
        return strategies[domain]["winning_strategy"]

    # Try Gemini for smart strategy selection
    if previous_errors and os.environ.get("GEMINI_API_KEY"):
        # Search web for how others automated this domain
        web_knowledge = ""
        try:
            search_prompt = f"How to automate job application on {domain}? What form fields does {domain} have? How to bypass CAPTCHA on {domain}? What selectors work for {domain} career page? Give me specific technical details: CSS selectors, button text, form structure, common issues."
            web_tips = ask_gemini(search_prompt)
            if web_tips:
                web_knowledge = f"\n\nKnown information about {domain} from AI knowledge:\n{web_tips[:500]}"
        except Exception:
            pass

        prompt = f"""You are a job application automation expert. I'm trying to apply to a job on domain "{domain}".

Previous {len(previous_errors)} attempts failed with these errors:
{json.dumps(previous_errors[-3:], indent=2)}
{web_knowledge}

Available strategy templates (pick one number 0-4 or suggest modifications):
0. standard_fill — fill all fields top-to-bottom, submit
1. slow_human — longer waits, random delays between fields
2. bottom_up_fill — fill from bottom to top
3. skip_optional — only fill required fields
4. multi_page_aggressive — handle multi-step forms with Next/Continue buttons

Based on the errors and the domain knowledge above, which strategy should I try next?
Also suggest specific CSS selectors or button text if you know them for this site.
Reply with ONLY a JSON object like:
{{"strategy_index": 2, "modifications": {{"wait_before_fill": 5.0, "extra_clicks": ["button.close-popup"], "custom_selectors": {{"submit": "button[data-testid=submit]"}}}}}}
"""
        response = ask_gemini(prompt)
        try:
            # Extract JSON from response
            match = re.search(r'\{[^{}]*\}', response)
            if match:
                suggestion = json.loads(match.group())
                idx = suggestion.get("strategy_index", attempt % len(STRATEGY_TEMPLATES))
                strategy = STRATEGY_TEMPLATES[idx % len(STRATEGY_TEMPLATES)].copy()
                mods = suggestion.get("modifications", {})
                strategy.update(mods)
                strategy["source"] = "gemini"
                return strategy
        except Exception:
            pass

    # Fallback: cycle through templates
    strategy = STRATEGY_TEMPLATES[attempt % len(STRATEGY_TEMPLATES)].copy()
    strategy["source"] = "template"
    return strategy


# ─── Core Solver ─────────────────────────────────────────────────────

# Field matching (from applier.py patterns)
FIELD_MAP = {
    "full name": "name", "your name": "name", "name": "name",
    "first name": "first_name", "given name": "first_name",
    "last name": "last_name", "surname": "last_name", "family": "last_name",
    "email": "email", "e-mail": "email",
    "phone": "phone", "mobile": "phone", "telephone": "phone",
    "city": "city", "location": "location",
    "state": "state", "zip": "zip", "postal": "zip",
    "country": "country", "linkedin": "linkedin",
    "github": "github", "portfolio": "github", "website": "linkedin",
}

KNOWN_ANSWERS = {
    "authorized": "Yes", "legally authorized": "Yes", "eligible to work": "Yes",
    "sponsorship": "No", "require sponsor": "No", "visa sponsor": "No",
    "relocate": "No", "start": "Immediately", "notice period": "2 weeks",
    "salary": "150000", "hourly": "75", "rate": "75",
    "hear about": "Online Job Board", "how did you": "Online Job Board",
    "gender": "Decline to state", "race": "Decline to state",
    "veteran": "I am not a protected veteran",
    "disability": "I do not wish to answer",
    "background check": "Yes", "consent": "Yes", "agree": "Yes",
    "remote": "Yes", "years of experience": "10+",
    "employment type": "Contract", "contract type": "Corp-to-Corp (C2C)",
}


def match_field_to_profile(label: str, profile: dict) -> str | None:
    """Match a field label to a profile value."""
    label_lower = label.lower().strip()
    for key, profile_key in FIELD_MAP.items():
        if key in label_lower:
            return profile.get(profile_key, "")
    # Try known answers
    for key, answer in KNOWN_ANSWERS.items():
        if key in label_lower:
            return answer
    return None


def attempt_apply(page, job: dict, strategy: dict, profile: dict, attempt_num: int) -> dict:
    """One attempt to apply to a job using a specific strategy. Returns result dict."""
    url = job["url"]
    result = {
        "attempt": attempt_num,
        "strategy": strategy["name"],
        "url": url,
        "status": "failed",
        "fields_found": 0,
        "fields_filled": 0,
        "errors": [],
        "screenshot": None,
        "timestamp": datetime.now().isoformat(),
    }

    try:
        # Navigate
        wait_time = strategy.get("wait_before_fill", 2.0)
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(wait_time)

        # Dismiss popups
        for text in ["Accept", "Accept All", "Accept Cookies", "Close", "Got it", "OK", "×"]:
            try:
                btn = page.locator(f'button:has-text("{text}")').first
                if btn.is_visible(timeout=1000):
                    btn.click()
                    time.sleep(0.5)
            except Exception:
                continue

        # Extra clicks from strategy (Gemini-suggested)
        for selector in strategy.get("extra_clicks", []):
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=2000):
                    el.click()
                    time.sleep(0.5)
            except Exception:
                pass

        # Check if page loaded and has a form
        page_text = page.inner_text("body", timeout=5000)[:3000]
        if any(kw in page_text.lower() for kw in ["404", "page not found", "no longer available",
                                                     "position has been filled", "this job is closed"]):
            result["status"] = "job_closed"
            result["errors"].append("Job is closed or page not found")
            return result

        # Read form fields
        fields = page.evaluate("""() => {
            const fields = [];
            document.querySelectorAll('input, select, textarea').forEach(el => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                if (rect.width < 5 || style.display === 'none') return;
                const labelEl = el.closest('label') || document.querySelector('label[for="'+el.id+'"]');
                fields.push({
                    tag: el.tagName.toLowerCase(),
                    type: el.type || 'text',
                    name: el.name || '',
                    id: el.id || '',
                    placeholder: el.placeholder || '',
                    ariaLabel: el.getAttribute('aria-label') || '',
                    label: labelEl ? labelEl.innerText.trim().substring(0,200) : '',
                    required: el.required,
                    selector: el.id ? '#'+el.id : (el.name ? '[name="'+el.name+'"]' : null),
                });
            });
            return fields;
        }""")

        result["fields_found"] = len(fields)

        if not fields:
            result["errors"].append("No form fields found on page")
            # Maybe it's behind a button
            for btn_text in ["Apply", "Apply Now", "Apply for this job", "Start Application"]:
                try:
                    btn = page.locator(f'a:has-text("{btn_text}"), button:has-text("{btn_text}")').first
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        time.sleep(3)
                        # Re-read fields
                        fields = page.evaluate("""() => {
                            const fields = [];
                            document.querySelectorAll('input, select, textarea').forEach(el => {
                                const rect = el.getBoundingClientRect();
                                const style = window.getComputedStyle(el);
                                if (rect.width < 5 || style.display === 'none') return;
                                const labelEl = el.closest('label') || document.querySelector('label[for="'+el.id+'"]');
                                fields.push({
                                    tag: el.tagName.toLowerCase(),
                                    type: el.type || 'text',
                                    name: el.name || '',
                                    id: el.id || '',
                                    placeholder: el.placeholder || '',
                                    ariaLabel: el.getAttribute('aria-label') || '',
                                    label: labelEl ? labelEl.innerText.trim().substring(0,200) : '',
                                    required: el.required,
                                    selector: el.id ? '#'+el.id : (el.name ? '[name="'+el.name+'"]' : null),
                                });
                            });
                            return fields;
                        }""")
                        result["fields_found"] = len(fields)
                        break
                except Exception:
                    continue

        if not fields:
            result["errors"].append("No form fields even after clicking Apply button")
            return result

        # Order fields based on strategy
        if strategy.get("fill_order") == "bottom_to_top":
            fields = list(reversed(fields))
        elif strategy.get("fill_order") == "required_first":
            fields = sorted(fields, key=lambda f: 0 if f.get("required") else 1)

        # Fill fields
        filled = 0
        inter_delay = strategy.get("inter_field_delay", 0.3)

        for field in fields:
            if not field.get("selector"):
                continue
            if field["type"] == "hidden":
                continue
            if field["type"] == "file":
                # Upload resume
                if strategy.get("try_file_upload") and RESUME_PATH.exists():
                    try:
                        page.locator(field["selector"]).set_input_files(str(RESUME_PATH))
                        filled += 1
                    except Exception:
                        pass
                continue

            # Determine value
            label = field.get("label") or field.get("placeholder") or field.get("ariaLabel") or field.get("name", "")
            value = match_field_to_profile(label, profile)

            if not value and strategy.get("skip_optional") and not field.get("required"):
                continue

            if not value:
                continue

            try:
                el = page.locator(field["selector"]).first
                if not el.is_visible(timeout=2000):
                    continue
                if field["tag"] == "select":
                    try:
                        el.select_option(label=value, timeout=3000)
                    except Exception:
                        try:
                            el.select_option(value=value, timeout=2000)
                        except Exception:
                            pass
                else:
                    el.click()
                    el.fill("")
                    el.fill(value)
                filled += 1
                time.sleep(random.uniform(0.1, inter_delay))
            except Exception as e:
                result["errors"].append(f"Fill {label[:30]}: {str(e)[:50]}")

        result["fields_filled"] = filled

        # Take screenshot after filling
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        ss_path = SCREENSHOTS_DIR / f"solve_{int(time.time())}_{attempt_num}.png"
        try:
            page.screenshot(path=str(ss_path), full_page=True)
            result["screenshot"] = str(ss_path)
        except Exception:
            pass

        # Handle multi-page if strategy says so
        if strategy.get("handle_multi_page"):
            for next_text in ["Next", "Continue", "Next Step"]:
                try:
                    btn = page.locator(f'button:has-text("{next_text}")').first
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        time.sleep(2)
                except Exception:
                    continue

        # Try to submit
        submitted = False
        for submit_text in strategy.get("click_submit_text", ["Submit", "Apply"]):
            try:
                btn = page.locator(f'button:has-text("{submit_text}"), input[type="submit"][value*="{submit_text}"]').first
                if btn.is_visible(timeout=3000):
                    btn.click()
                    time.sleep(3)
                    submitted = True
                    break
            except Exception:
                continue

        if not submitted:
            # Try generic submit button
            try:
                btn = page.locator('button[type="submit"], input[type="submit"]').first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    time.sleep(3)
                    submitted = True
            except Exception:
                pass

        if not submitted:
            result["errors"].append("Could not find/click submit button")
            return result

        # Check for success signals
        time.sleep(2)
        post_text = page.inner_text("body", timeout=5000)[:2000].lower()
        success_signals = ["thank you", "application received", "successfully submitted",
                          "we received your application", "application has been submitted",
                          "you have applied", "thanks for applying"]
        error_signals = ["error", "required field", "please fill", "invalid",
                        "something went wrong", "try again"]

        if any(sig in post_text for sig in success_signals):
            result["status"] = "submitted"
        elif any(sig in post_text for sig in error_signals):
            # Read error messages
            errors_on_page = page.evaluate("""() => {
                const errors = [];
                document.querySelectorAll('.error, [class*="error"], [role="alert"], [class*="invalid"]').forEach(el => {
                    const text = el.innerText.trim();
                    if (text && text.length < 200) errors.push(text);
                });
                return errors;
            }""")
            result["errors"].extend(errors_on_page[:5])
            result["status"] = "form_errors"
        else:
            # Ambiguous — check if URL changed (often means success)
            if page.url != url:
                result["status"] = "submitted"
            else:
                result["status"] = "unknown"

    except PwTimeout:
        result["status"] = "timeout"
        result["errors"].append("Page load or action timed out")
    except Exception as e:
        result["status"] = "error"
        result["errors"].append(str(e)[:200])

    return result


# ─── Main Solver Loop ────────────────────────────────────────────────

def solve_job(job: dict, profile: dict) -> dict:
    """Try up to MAX_ATTEMPTS strategies on a single job. Returns final result."""
    url = job.get("url", "")
    domain = urlparse(url).netloc
    previous_errors = []
    final_result = {"url": url, "domain": domain, "attempts": [], "final_status": "exhausted"}

    print(f"\n{'='*60}")
    print(f"  🧩 Solving: {job.get('title', '?')} @ {job.get('company', '?')}")
    print(f"  🌐 {url}")
    print(f"{'='*60}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        for attempt in range(MAX_ATTEMPTS):
            strategy = get_next_strategy(attempt, domain, previous_errors)
            print(f"\n  Attempt {attempt+1}/{MAX_ATTEMPTS}: {strategy.get('description', strategy['name'])}")

            result = attempt_apply(page, job, strategy, profile, attempt + 1)
            final_result["attempts"].append(result)

            print(f"    Status: {result['status']} | Fields: {result['fields_filled']}/{result['fields_found']}")
            if result["errors"]:
                print(f"    Errors: {result['errors'][:2]}")

            if result["status"] == "submitted":
                final_result["final_status"] = "submitted"
                final_result["winning_strategy"] = strategy
                print(f"\n  ✅ SUCCESS on attempt {attempt+1}!")
                break
            elif result["status"] == "job_closed":
                final_result["final_status"] = "job_closed"
                print(f"  ⛔ Job is closed/removed")
                break

            previous_errors.append({
                "attempt": attempt + 1,
                "strategy": strategy["name"],
                "status": result["status"],
                "errors": result["errors"][:3],
                "fields_filled": result["fields_filled"],
                "fields_found": result["fields_found"],
            })

            # Wait between attempts
            time.sleep(random.uniform(2, 4))

        browser.close()

    return final_result


def update_strategies(result: dict):
    """If we found a winning strategy, save it for future use."""
    if result["final_status"] != "submitted":
        return
    domain = result["domain"]
    strategies = load_strategies()
    strategies[domain] = {
        "winning_strategy": result.get("winning_strategy", {}),
        "last_success": datetime.now().isoformat(),
        "url_example": result["url"],
    }
    save_strategies(strategies)
    print(f"  💾 Saved winning strategy for {domain}")


def main():
    parser = argparse.ArgumentParser(description="Self-improving job solver")
    parser.add_argument("--max-jobs", type=int, default=5, help="Max jobs to solve per run")
    args = parser.parse_args()

    print(f"\n🧠 Self-Improving Job Solver — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # Load data
    unsolved = load_unsolved()
    if not unsolved:
        print("  No unsolved jobs found. Nothing to do.")
        return

    profile = load_profile()
    solve_log = load_solve_log()
    solved_urls = {entry["url"] for entry in solve_log if entry.get("final_status") in ("submitted", "job_closed", "exhausted")}

    # Filter out already-attempted jobs
    to_solve = [j for j in unsolved if j.get("url") not in solved_urls]
    print(f"  📋 {len(unsolved)} unsolved jobs, {len(to_solve)} not yet attempted")

    if not to_solve:
        print("  All jobs already attempted. Waiting for new unsolved jobs.")
        return

    # Process up to max_jobs
    results = []
    for i, job in enumerate(to_solve[: args.max_jobs]):
        try:
            result = solve_job(job, profile)
            results.append(result)
            solve_log.append({
                "url": result["url"],
                "domain": result["domain"],
                "final_status": result["final_status"],
                "attempts_count": len(result["attempts"]),
                "date": datetime.now().isoformat(),
            })
            # Save winning strategy
            update_strategies(result)
        except Exception as e:
            print(f"  ❌ Solver crashed on job {i+1}: {e}")
            traceback.print_exc()

    # Remove solved/exhausted jobs from unsolved list
    solved_in_run = {r["url"] for r in results if r["final_status"] in ("submitted", "job_closed")}
    remaining = [j for j in unsolved if j.get("url") not in solved_in_run]
    save_unsolved(remaining)
    save_solve_log(solve_log)

    # Summary
    submitted = sum(1 for r in results if r["final_status"] == "submitted")
    closed = sum(1 for r in results if r["final_status"] == "job_closed")
    exhausted = sum(1 for r in results if r["final_status"] == "exhausted")
    print(f"\n{'='*60}")
    print(f"  📊 Results: {submitted} submitted, {closed} closed, {exhausted} exhausted")
    print(f"  📋 Remaining unsolved: {len(remaining)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
