"""Self-learning browser applier.

Strategy:
1. Open page → read EVERY element (inputs, labels, buttons, text)
2. Build a map of what the page wants
3. Fill fields from profile using multiple matching strategies
4. If submit fails → analyze WHY → try different approach
5. Retry up to 3 times, each time smarter than the last
6. Save what worked for next time
"""
import json, os, re, time, random
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

PROFILE_PATH = Path(__file__).parent.parent / "config" / "profile.json"
RESUME_PATH = Path(__file__).parent.parent / "resume.pdf"
SCREENSHOTS = Path(__file__).parent.parent / "screenshots"
LEARNED_FILE = Path(__file__).parent.parent / "data" / "learned.json"
MAX_RETRIES = 3

# Maps label keywords → profile keys
FIELD_MAP = {
    "full name": "name", "your name": "name", "name": "name",
    "first name": "first_name", "given name": "first_name",
    "last name": "last_name", "surname": "last_name", "family": "last_name",
    "email": "email", "e-mail": "email",
    "phone": "phone", "mobile": "phone", "telephone": "phone", "cell": "phone",
    "city": "city", "location": "location", "where are you": "location",
    "state": "state", "province": "state",
    "zip": "zip", "postal": "zip",
    "country": "country",
    "linkedin": "linkedin",
    "github": "github",
    "portfolio": "github",
    "website": "linkedin",
    "company": "company", "current company": "company", "employer": "company", "organization": "company",
}

KNOWN_ANSWERS = {
    "authorized": "Yes", "legally authorized": "Yes", "eligible to work": "Yes", "work in the u": "Yes",
    "sponsorship": "No", "require sponsor": "No", "visa sponsor": "No",
    "relocate": "No", "willing to relocate": "No",
    "start": "Immediately", "when can you": "Immediately", "available": "Immediately",
    "salary": "150000", "compensation": "150000", "expected pay": "150000",
    "hourly": "75", "rate": "75",
    "hear about": "Online Job Board", "how did you": "Online Job Board", "source": "Job Board",
    "gender": "Decline", "race": "Decline", "ethnicity": "Decline", "demographic": "Decline",
    "veteran": "not a protected veteran", "disability": "do not wish to answer",
    "background check": "Yes", "consent": "Yes", "agree": "Yes",
}


def load_profile():
    p = json.loads(PROFILE_PATH.read_text())
    p.setdefault("company", "")
    p.setdefault("location", f"{p.get('city','')}, {p.get('state','')}")
    return p


def load_learned():
    if LEARNED_FILE.exists():
        try:
            return json.loads(LEARNED_FILE.read_text())
        except Exception:
            pass
    return {"winning_selectors": {}, "success_count": {}, "fail_reasons": {}}


def save_learned(data):
    LEARNED_FILE.parent.mkdir(parents=True, exist_ok=True)
    LEARNED_FILE.write_text(json.dumps(data, indent=2))


def snap(page, name):
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    p = SCREENSHOTS / f"{int(time.time())}_{name}.png"
    try:
        page.screenshot(path=str(p), full_page=True)
    except Exception:
        pass
    return str(p)


def wait(a=0.3, b=1.0):
    time.sleep(random.uniform(a, b))


# ─── STEP 1: Read the entire page ───

def read_page(page) -> dict:
    """Read EVERY element on the page. Returns full page analysis."""
    return page.evaluate("""() => {
        const result = {inputs: [], selects: [], textareas: [], buttons: [], fileInputs: [], labels: [], pageText: ''};

        // All inputs
        document.querySelectorAll('input').forEach(el => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            if (rect.width < 5 || style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return;
            const labelEl = el.closest('label') || document.querySelector('label[for="'+el.id+'"]');
            result.inputs.push({
                type: el.type || 'text',
                name: el.name || '',
                id: el.id || '',
                placeholder: el.placeholder || '',
                ariaLabel: el.getAttribute('aria-label') || '',
                label: labelEl ? labelEl.innerText.trim().substring(0,200) : '',
                value: el.value || '',
                required: el.required,
                selector: el.id ? '#'+el.id : el.name ? '[name="'+el.name+'"]' : null,
            });
        });

        // Selects
        document.querySelectorAll('select').forEach(el => {
            const rect = el.getBoundingClientRect();
            if (rect.width < 5) return;
            const labelEl = el.closest('label') || document.querySelector('label[for="'+el.id+'"]');
            const options = Array.from(el.options).map(o => ({text: o.text.trim(), value: o.value}));
            result.selects.push({
                name: el.name || '', id: el.id || '',
                label: labelEl ? labelEl.innerText.trim().substring(0,200) : '',
                options: options,
                selector: el.id ? '#'+el.id : el.name ? '[name="'+el.name+'"]' : null,
            });
        });

        // Textareas
        document.querySelectorAll('textarea').forEach(el => {
            const rect = el.getBoundingClientRect();
            if (rect.width < 5) return;
            const labelEl = el.closest('label') || document.querySelector('label[for="'+el.id+'"]');
            result.textareas.push({
                name: el.name || '', id: el.id || '',
                label: labelEl ? labelEl.innerText.trim().substring(0,200) : '',
                placeholder: el.placeholder || '',
                selector: el.id ? '#'+el.id : el.name ? '[name="'+el.name+'"]' : null,
            });
        });

        // File inputs (even hidden ones — they're used for resume upload)
        document.querySelectorAll('input[type="file"]').forEach(el => {
            result.fileInputs.push({
                name: el.name || '', id: el.id || '',
                accept: el.accept || '',
                selector: el.id ? '#'+el.id : el.name ? '[name="'+el.name+'"]' : 'input[type="file"]',
            });
        });

        // Buttons
        document.querySelectorAll('button, input[type="submit"], a[role="button"]').forEach(el => {
            const rect = el.getBoundingClientRect();
            if (rect.width < 5) return;
            result.buttons.push({
                text: el.innerText.trim().substring(0,100) || el.value || '',
                type: el.type || '',
                selector: el.id ? '#'+el.id : null,
            });
        });

        // Page text (for understanding context)
        result.pageText = document.body.innerText.substring(0, 3000);
        return result;
    }""")


# ─── STEP 2: Match fields to profile ───

def match_field(label_text, name_attr, placeholder, aria_label):
    """Match a form field to a profile key using all available info."""
    combined = f"{label_text} {name_attr} {placeholder} {aria_label}".lower()
    # Check longest patterns first (more specific = better match)
    sorted_patterns = sorted(FIELD_MAP.keys(), key=len, reverse=True)
    for pattern in sorted_patterns:
        if pattern in combined:
            return FIELD_MAP[pattern]
    return None


def match_answer(label_text):
    """Match a question to a known answer."""
    lower = label_text.lower()
    for pattern, answer in KNOWN_ANSWERS.items():
        if pattern in lower:
            return answer
    return None


# ─── STEP 3: Fill the form ───

def fill_form(page, page_data, profile, learned, domain) -> dict:
    """Fill every field we can. Returns what we filled and what we couldn't."""
    filled = []
    unfilled = []

    # Check if we have learned selectors for this domain
    known = learned.get("winning_selectors", {}).get(domain, {})

    # 1. Upload resume
    for fi in page_data["fileInputs"]:
        if RESUME_PATH.exists():
            try:
                page.locator(fi["selector"]).set_input_files(str(RESUME_PATH))
                filled.append(("resume", fi["selector"]))
                wait(1, 2)
            except Exception:
                # Try file chooser
                try:
                    with page.expect_file_chooser(timeout=3000) as fc:
                        page.click('text=/attach|upload|resume|cv/i')
                    fc.value.set_files(str(RESUME_PATH))
                    filled.append(("resume", "file_chooser"))
                except Exception:
                    unfilled.append(("resume", "all methods failed"))

    # 2. Fill text inputs
    for inp in page_data["inputs"]:
        if inp["type"] in ("hidden", "file", "submit", "button", "checkbox", "radio"):
            continue
        sel = inp["selector"]
        if not sel:
            continue

        # Check learned selectors first
        if sel in known:
            profile_key = known[sel]
            value = profile.get(profile_key, "")
            if value:
                try:
                    page.locator(sel).fill(str(value))
                    filled.append((profile_key, sel))
                    wait(0.2, 0.5)
                    continue
                except Exception:
                    pass

        # Match by label/name/placeholder/aria
        profile_key = match_field(inp["label"], inp["name"], inp["placeholder"], inp["ariaLabel"])
        if profile_key:
            value = profile.get(profile_key, "")
            if value:
                # Fix format based on field type
                from src.page_doctor import fix_field_format
                value = fix_field_format(inp["label"] or inp["name"], str(value))
                try:
                    page.locator(sel).fill(str(value))
                    filled.append((profile_key, sel))
                    # Learn this selector
                    learned.setdefault("winning_selectors", {}).setdefault(domain, {})[sel] = profile_key
                    wait(0.2, 0.5)
                    continue
                except Exception as e:
                    unfilled.append((profile_key, f"{sel}: {e}"))
                    continue

        # Check if it's a question we know the answer to
        answer = match_answer(inp["label"] or inp["placeholder"] or inp["ariaLabel"])
        if answer:
            try:
                page.locator(sel).fill(answer)
                filled.append(("answer:" + inp["label"][:30], sel))
                wait(0.2, 0.5)
                continue
            except Exception:
                pass

        # Unknown field — ask AI for help
        if inp["label"] or inp["placeholder"]:
            from src.ai_fallback import ask_ai_about_field
            ai_answer = ask_ai_about_field(
                inp["label"] or inp["placeholder"] or inp["ariaLabel"],
                inp["type"],
            )
            if ai_answer:
                try:
                    page.locator(sel).fill(ai_answer)
                    filled.append(("ai:" + (inp["label"] or inp["name"])[:30], sel))
                    learned.setdefault("winning_selectors", {}).setdefault(domain, {})[sel] = "ai:" + ai_answer[:50]
                    wait(0.2, 0.5)
                    continue
                except Exception:
                    pass

        if inp["required"]:
            unfilled.append(("unknown_required", f"{sel} label='{inp['label'][:50]}'"))

    # 3. Fill select dropdowns
    for sel_data in page_data["selects"]:
        sel = sel_data["selector"]
        if not sel:
            continue
        answer = match_answer(sel_data["label"])
        if answer:
            # Find best matching option
            for opt in sel_data["options"]:
                if answer.lower() in opt["text"].lower() or "decline" in opt["text"].lower():
                    try:
                        page.locator(sel).select_option(label=opt["text"])
                        filled.append(("select:" + sel_data["label"][:30], sel))
                        wait(0.2, 0.5)
                    except Exception:
                        pass
                    break

    # 4. Fill textareas (cover letter, additional info)
    for ta in page_data["textareas"]:
        sel = ta["selector"]
        if not sel:
            continue
        label = (ta["label"] or ta["placeholder"]).lower()
        if "cover" in label or "letter" in label:
            from src.ai_fallback import ask_ai_cover_letter
            cover = ask_ai_cover_letter(
                profile.get("title", "Java Developer"),
                profile.get("company", ""),
                page_data.get("pageText", "")[:500],
            )
            try:
                page.locator(sel).fill(cover)
                filled.append(("cover_letter", sel))
            except Exception:
                pass
        elif "additional" in label or "comment" in label or "note" in label:
            try:
                page.locator(sel).fill("Available immediately for C2C contract. Green Card holder, no sponsorship needed.")
                filled.append(("additional_info", sel))
            except Exception:
                pass

    # 5. Handle checkboxes (consent, agree, etc.)
    for inp in page_data["inputs"]:
        if inp["type"] != "checkbox":
            continue
        label = inp["label"].lower()
        if any(k in label for k in ["agree", "consent", "acknowledge", "confirm", "accept"]):
            # Skip non-compete
            if any(k in label for k in ["non-compete", "noncompete", "exclusiv"]):
                unfilled.append(("MANUAL_REVIEW", inp["label"][:50]))
                continue
            try:
                sel = inp["selector"] or f'input[type="checkbox"]'
                page.locator(sel).first.check()
                filled.append(("checkbox:" + label[:30], sel))
            except Exception:
                pass

    return {"filled": filled, "unfilled": unfilled}


# ─── STEP 4: Submit and verify ───

def submit_and_verify(page, page_data, original_url) -> dict:
    """Find submit button, click it, verify success."""
    # Find submit button
    submit_texts = ["submit application", "submit", "apply now", "apply", "send application", "send", "complete"]
    for btn in page_data["buttons"]:
        btn_lower = btn["text"].lower()
        for st in submit_texts:
            if st in btn_lower:
                try:
                    if btn["selector"]:
                        page.locator(btn["selector"]).click()
                    else:
                        page.locator(f'button:has-text("{btn["text"]}")').first.click()
                    wait(2, 4)

                    # Check success
                    url = page.url.lower()
                    try:
                        text = page.locator("body").inner_text(timeout=5000).lower()
                    except Exception:
                        text = ""

                    success_signals = ["thank", "success", "received", "submitted", "confirmation", "applied", "complete"]
                    if any(s in url for s in success_signals) or any(s in text for s in success_signals):
                        return {"submitted": True, "method": btn["text"]}

                    error_signals = ["error", "required", "invalid", "please fill", "missing"]
                    errors = [s for s in error_signals if s in text]
                    if errors:
                        return {"submitted": False, "reason": f"Form errors: {errors}"}

                    # URL changed = probably success
                    if url != original_url.lower().rstrip("/"):
                        return {"submitted": True, "method": "url_changed"}

                    return {"submitted": False, "reason": "No success signal after submit"}
                except Exception as e:
                    return {"submitted": False, "reason": str(e)[:200]}

    return {"submitted": False, "reason": "No submit button found"}


# ─── MAIN: The self-learning retry loop ───

def apply_to_job(page, profile, job, learned, dry_run=False) -> dict:
    """Apply to one job. Retries up to 3 times, learning from each failure."""
    url = job.get("url", "")
    domain = re.sub(r'https?://(www\.)?', '', url).split('/')[0]
    result = {"url": url, "title": job.get("title", ""), "company": job.get("company", ""),
              "status": "pending", "attempts": [], "fields_filled": 0}

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"    Attempt {attempt}/{MAX_RETRIES}")
        attempt_result = {"attempt": attempt, "filled": 0, "unfilled": 0, "error": None}

        try:
            # Navigate
            apply_url = url.rstrip("/")
            if "lever.co" in apply_url and not apply_url.endswith("/apply"):
                apply_url += "/apply"
            page.goto(apply_url, wait_until="networkidle", timeout=30000)
            wait(1, 2)

            # Check if page exists
            if page.locator("text=/not found|404|expired|closed|no longer/i").count() > 0:
                result["status"] = "job_closed"
                snap(page, f"closed_{attempt}")
                break

            # DOCTOR: dismiss popups/cookie banners first
            from src.page_doctor import dismiss_popups, read_errors, fix_errors_and_retry, detect_captcha, detect_multi_step, click_next_button, fix_field_format
            dismissed = dismiss_popups(page)
            if dismissed:
                print(f"      Dismissed {dismissed} popups/banners")

            # Check for CAPTCHA
            if detect_captcha(page):
                result["status"] = "captcha_blocked"
                snap(page, f"captcha_{attempt}")
                print(f"      ⚠️  CAPTCHA detected — skipping this job")
                break

            # READ the entire page
            page_data = read_page(page)
            snap(page, f"read_{attempt}")
            print(f"      Found: {len(page_data['inputs'])} inputs, {len(page_data['selects'])} selects, "
                  f"{len(page_data['fileInputs'])} file uploads, {len(page_data['buttons'])} buttons")

            # FILL the form
            fill_result = fill_form(page, page_data, profile, learned, domain)
            attempt_result["filled"] = len(fill_result["filled"])
            attempt_result["unfilled"] = len(fill_result["unfilled"])
            snap(page, f"filled_{attempt}")
            print(f"      Filled {attempt_result['filled']} fields, {attempt_result['unfilled']} unfilled")

            if attempt_result["filled"] < 2:
                attempt_result["error"] = "Too few fields filled"
                result["attempts"].append(attempt_result)
                # Learn: log what fields we couldn't match
                learned.setdefault("fail_reasons", {}).setdefault(domain, []).append(
                    {"attempt": attempt, "unfilled": [u[1] for u in fill_result["unfilled"][:5]]}
                )
                # On retry 2+, ask AI to analyze the full page
                if attempt >= 2 and fill_result["unfilled"]:
                    print(f"      🤖 Asking AI to analyze page...")
                    from src.ai_fallback import ask_ai_about_page
                    unfilled_data = []
                    for inp in page_data["inputs"]:
                        if inp["selector"] and not any(inp["selector"] == f[1] for f in fill_result["filled"]):
                            unfilled_data.append(inp)
                    ai_suggestions = ask_ai_about_page(page_data.get("pageText", ""), unfilled_data)
                    for sel, value in ai_suggestions.items():
                        try:
                            page.locator(sel).fill(str(value))
                            fill_result["filled"].append(("ai_page:" + sel[:20], sel))
                            attempt_result["filled"] += 1
                            wait(0.2, 0.5)
                        except Exception:
                            pass
                    if attempt_result["filled"] >= 2:
                        print(f"      🤖 AI helped fill {len(ai_suggestions)} more fields!")
                        snap(page, f"ai_helped_{attempt}")
                        # Continue to submit instead of retrying
                    else:
                        print(f"      ⚠️  Only {attempt_result['filled']} fields — retrying...")
                        wait(1, 2)
                        continue
                else:
                    print(f"      ⚠️  Only {attempt_result['filled']} fields — retrying...")
                    wait(1, 2)
                    continue

            if dry_run:
                result["status"] = "dry_run"
                result["fields_filled"] = attempt_result["filled"]
                snap(page, f"dryrun_{attempt}")
                print(f"      🔒 DRY RUN — {attempt_result['filled']} fields filled")
                result["attempts"].append(attempt_result)
                save_learned(learned)
                return result

            # SUBMIT
            submit_result = submit_and_verify(page, page_data, url)
            snap(page, f"submit_{attempt}")

            if submit_result["submitted"]:
                result["status"] = "submitted"
                result["fields_filled"] = attempt_result["filled"]
                learned.setdefault("success_count", {})[domain] = learned.get("success_count", {}).get(domain, 0) + 1
                print(f"      ✅ SUBMITTED via '{submit_result.get('method', '?')}'")
                result["attempts"].append(attempt_result)
                save_learned(learned)
                return result
            else:
                attempt_result["error"] = submit_result["reason"]
                print(f"      ❌ Submit failed: {submit_result['reason']}")
                # DOCTOR: read error messages and try to fix
                errors = read_errors(page)
                if errors:
                    print(f"      🔧 Found {len(errors)} errors: {errors[:3]}")
                    fixed = fix_errors_and_retry(page, profile, errors)
                    if fixed:
                        print(f"      🔧 Fixed {fixed} fields — will retry submit")
                        # Save what errors we saw for learning
                        learned.setdefault("error_patterns", {}).setdefault(domain, []).extend(errors[:5])
                learned.setdefault("fail_reasons", {}).setdefault(domain, []).append(
                    {"attempt": attempt, "reason": submit_result["reason"], "errors": errors[:3]}
                )

        except Exception as e:
            attempt_result["error"] = str(e)[:200]
            print(f"      ❌ Error: {str(e)[:100]}")
            snap(page, f"error_{attempt}")

        result["attempts"].append(attempt_result)
        wait(2, 4)

    # All retries exhausted
    if result["status"] == "pending":
        result["status"] = "failed_all_retries"
    save_learned(learned)
    return result


def run_applications(jobs: list[dict], dry_run: bool = True, max_apps: int = 10) -> list[dict]:
    """Apply to multiple jobs with self-learning."""
    profile = load_profile()
    learned = load_learned()
    results = []

    try:
        from playwright_stealth import Stealth
        ctx = Stealth().use_sync(sync_playwright())
    except ImportError:
        ctx = sync_playwright()

    with ctx as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080}, locale="en-US", timezone_id="America/Denver",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        applied = 0

        for job in jobs:
            if applied >= max_apps:
                break
            print(f"\n  {'='*50}")
            print(f"  {job.get('title','?')} @ {job.get('company','?')}")

            r = apply_to_job(page, profile, job, learned, dry_run)
            results.append(r)
            if r["status"] in ("submitted", "dry_run"):
                applied += 1
            wait(3, 6)

        browser.close()

    save_learned(learned)
    ok = sum(1 for r in results if r["status"] in ("submitted", "dry_run"))
    print(f"\n  📊 {ok}/{len(results)} applied | Learned selectors for {len(learned.get('winning_selectors', {}))} domains")
    return results
