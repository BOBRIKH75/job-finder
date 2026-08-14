"""Self-learning browser applier.

Strategy:
1. Pre-check URL with stealth toolkit (curl_cffi → seleniumbase_uc → camoufox)
2. If blocked, harvest cookies with stealth tools and inject into Playwright
3. Open page → read EVERY element (inputs, labels, buttons, text)
4. Build a map of what the page wants
5. Fill fields from profile using multiple matching strategies
6. If submit fails → analyze WHY → try different approach
7. Retry up to 3 times, each time smarter than the last
8. Save what worked for next time
"""
import json, os, re, time, random
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
import cloakbrowser
from src.stealth_toolkit import stealth_fetch, fetch_curl_cffi, list_available_tools, StealthResult

PROFILE_PATH = Path(__file__).parent.parent / "config" / "profile.json"
RESUME_PATH = Path(__file__).parent.parent / "resume.pdf"
SCREENSHOTS = Path(__file__).parent.parent / "screenshots"
LEARNED_FILE = Path(__file__).parent.parent / "data" / "learned.json"
INDEED_COOKIES_FILE = Path(__file__).parent.parent / "data" / "indeed_cookies.json"
MAX_RETRIES = 1


def load_indeed_cookies() -> list[dict]:
    """Load Indeed session cookies (saved locally or from CI secret)."""
    # From file (local)
    if INDEED_COOKIES_FILE.exists():
        return json.loads(INDEED_COOKIES_FILE.read_text())
    # From env var (CI — base64 encoded)
    encoded = os.environ.get("INDEED_COOKIES", "")
    if encoded:
        import base64
        return json.loads(base64.b64decode(encoded))
    return []

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


def wait(a=0.2, b=0.5):
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
    skip_texts = ["linkedin", "google", "facebook", "twitter", "sign in", "log in", "dismiss"]
    for btn in page_data["buttons"]:
        btn_lower = btn["text"].lower()
        if any(s in btn_lower for s in skip_texts):
            continue
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

def apply_to_job(page, profile, job, learned, dry_run=False, db=None) -> dict:
    """Apply to one job. Retries up to 3 times, learning from each failure."""
    url = job.get("url", "")
    domain = re.sub(r'https?://(www\.)?', '', url).split('/')[0]
    result = {"url": url, "title": job.get("title", ""), "company": job.get("company", ""),
              "status": "pending", "attempts": [], "fields_filled": 0}

    # Check if this domain is known to be blocked
    if db:
        from src.learning_engine import is_blocked_site
        blocked_reason = is_blocked_site(db, domain)
        if blocked_reason:
            result["status"] = "known_blocked"
            print(f"    ⏭️  Skipping {domain} — previously blocked: {blocked_reason}")
            return result

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"    Attempt {attempt}/{MAX_RETRIES}")
        attempt_result = {"attempt": attempt, "filled": 0, "unfilled": 0, "error": None}
        page_data = None

        try:
            # Navigate
            apply_url = url.rstrip("/")
            if "lever.co" in apply_url and not apply_url.endswith("/apply"):
                apply_url += "/apply"
            if "greenhouse.io" in apply_url and "#app" not in apply_url:
                apply_url += "#app"
            if "job-boards.greenhouse.io" in apply_url and "#app" not in apply_url:
                apply_url += "#app"
            if "ashbyhq.com" in apply_url and not apply_url.endswith("/application"):
                apply_url += "/application"
            page.goto(apply_url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(3000)  # let JS render forms
            wait(1, 2)

            # --- Multi-step navigation: dismiss cookie/consent, find apply forms ---
            # Dismiss cookie consent / popups before anything else
            for dismiss_sel in [
                'button:has-text("Accept")', 'button:has-text("Accept All")',
                'button:has-text("I agree")', 'button:has-text("Got it")',
                'button:has-text("OK")', 'button:has-text("Close")',
                '[id*="cookie"] button', '[class*="cookie"] button',
                '[id*="consent"] button', '[class*="consent"] button',
            ]:
                try:
                    loc = page.locator(dismiss_sel).first
                    if loc.is_visible(timeout=500):
                        loc.click()
                        wait(0.3, 0.6)
                except Exception:
                    pass

            # If no form inputs visible, try clicking Apply/Submit buttons to reach the form
            for nav_step in range(3):
                input_count = page.locator('input:not([type="hidden"])').count()
                textarea_count = page.locator('textarea').count()
                if input_count + textarea_count >= 2:
                    break  # We have a form
                # Try clicking an Apply button
                apply_clicked = False
                for btn_text in ["Apply Now", "Apply", "Apply for this job", "Submit Application", "Start Application"]:
                    try:
                        btn = page.locator(f'a:has-text("{btn_text}"), button:has-text("{btn_text}")').first
                        if btn.is_visible(timeout=1000):
                            btn.click()
                            page.wait_for_timeout(2000)
                            apply_clicked = True
                            break
                    except Exception:
                        continue
                if not apply_clicked:
                    # Check for iframe with form inputs
                    for frame in page.frames:
                        if frame == page.main_frame:
                            continue
                        try:
                            if frame.locator('input:not([type="hidden"])').count() >= 2:
                                page = frame  # Switch to iframe for form filling
                                apply_clicked = True
                                break
                        except Exception:
                            continue
                if not apply_clicked:
                    break  # Nothing more to try

            # Check if page exists
            if page.locator("text=/not found|404|expired|closed|no longer/i").count() > 0:
                result["status"] = "job_closed"
                snap(page, f"closed_{attempt}")
                break

            # DOCTOR: dismiss popups/cookie banners first
            from src.page_doctor import dismiss_popups, read_errors, fix_errors_and_retry, detect_captcha, detect_multi_step, click_next_button, fix_field_format, solve_turnstile_via_docker, solve_captcha
            dismissed = dismiss_popups(page)
            if dismissed:
                print(f"      Dismissed {dismissed} popups/banners")

            # Wait longer for JS-heavy pages (Greenhouse, Workday)
            if any(s in apply_url for s in ["greenhouse", "workday", "myworkday", "ashby"]):
                page.wait_for_timeout(3000)

            # Handle iframe-embedded forms (Greenhouse, Workday)
            main_page = page
            input_count = page.locator('input:not([type="hidden"])').count()
            if input_count < 2:
                for frame in page.frames:
                    if frame == page.main_frame:
                        continue
                    try:
                        frame_inputs = frame.locator('input:not([type="hidden"])').count()
                        if frame_inputs >= 2:
                            page = frame
                            print(f"      📋 Switched to iframe ({frame_inputs} inputs)")
                            break
                    except Exception:
                        continue

            # Hide invisible CAPTCHA overlays (hCaptcha, reCAPTCHA) that block clicks
            page.evaluate("""() => {
                document.querySelectorAll('.h-captcha, [id=h-captcha], .g-recaptcha').forEach(e => {
                    if (e.offsetHeight < 80) e.style.display = 'none';
                });
            }""")

            # Check for CAPTCHA — try full solve chain (Turnstile + reCAPTCHA v2/v3)
            if detect_captcha(page):
                solved = solve_captcha(page, apply_url)
                if solved:
                    print(f"      🔓 CAPTCHA solved — continuing with application")
                    wait(1, 2)
                else:
                    result["status"] = "captcha_blocked"
                    snap(page, f"captcha_{attempt}")
                    if db:
                        from src.learning_engine import learn_blocked_site
                        learn_blocked_site(db, domain, "captcha")
                    print(f"      ⚠️  CAPTCHA unsolvable — blocking domain")
                    break

            # READ the entire page
            page_data = read_page(page)
            snap(page, f"read_{attempt}")
            print(f"      Found: {len(page_data['inputs'])} inputs, {len(page_data['selects'])} selects, "
                  f"{len(page_data['fileInputs'])} file uploads, {len(page_data['buttons'])} buttons")

            # If no form, try clicking Apply button (Indeed, Dice, company pages)
            if len(page_data['inputs']) < 3:
                apply_texts = ["apply now", "apply", "apply for this job", "submit application", "easy apply"]
                for btn in page_data.get("buttons", []):
                    if any(t in btn.get("text", "").lower() for t in apply_texts):
                        try:
                            sel = btn.get("selector") or f'button:has-text("{btn["text"][:20]}")'
                            page.locator(sel).first.click(timeout=5000)
                            page.wait_for_timeout(3000)
                            dismiss_popups(page)
                            page_data = read_page(page)
                            print(f"      Clicked '{btn['text'][:20]}' → {len(page_data['inputs'])} inputs now")
                            break
                        except Exception:
                            continue

            # FILL the form (loop for multi-step)
            all_filled = []
            all_unfilled = []
            step = 1
            while True:
                fill_result = fill_form(page, page_data, profile, learned, domain)
                all_filled.extend(fill_result["filled"])
                all_unfilled.extend(fill_result["unfilled"])
                print(f"      Step {step}: filled {len(fill_result['filled'])}, unfilled {len(fill_result['unfilled'])}")

                # Check for multi-step form — click Next/Continue if present
                if detect_multi_step(page) and click_next_button(page):
                    step += 1
                    print(f"      ➡️  Advanced to step {step}")
                    snap(page, f"step{step}_{attempt}")
                    dismiss_popups(page)
                    page_data = read_page(page)
                    if not page_data["inputs"] and not page_data["selects"] and not page_data["textareas"]:
                        break  # No more fields on this step
                    continue
                break

            fill_result = {"filled": all_filled, "unfilled": all_unfilled}
            attempt_result["filled"] = len(all_filled)
            attempt_result["unfilled"] = len(all_unfilled)
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
                # LEARN: save everything that worked to DB
                if db:
                    from src.learning_engine import learn_from_success, learn_selector
                    learn_from_success(db, domain, url, [f[1] for f in fill_result["filled"]], attempt_result["filled"])
                    for profile_key, sel in fill_result["filled"]:
                        if not profile_key.startswith("ai:") and not profile_key.startswith("checkbox:"):
                            learn_selector(db, domain, sel, profile_key, worked=True)
                result["attempts"].append(attempt_result)
                save_learned(learned)
                return result
            else:
                attempt_result["error"] = submit_result["reason"]
                print(f"      ❌ Submit failed: {submit_result['reason']}")
                # LEARN: save failure to DB
                # DOCTOR: read error messages and try to fix
                errors = read_errors(page)
                if db:
                    from src.learning_engine import learn_from_failure
                    learn_from_failure(db, domain, url, [submit_result["reason"]] + errors, attempt)
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

            # On last attempt, use visual analysis
            if attempt == MAX_RETRIES:
                print(f"      👁️ Last resort: visual analysis...")
                from src.visual_analyzer import visual_fill_attempt
                visual = visual_fill_attempt(page)
                if visual["fields"]:
                    print(f"      👁️ AI Vision found {len(visual['fields'])} fields")
                    for f in visual["fields"]:
                        print(f"         → {f.get('field','?')}: {f.get('value','?')}")
                    # Try to fill using AI vision suggestions
                    for f in visual["fields"]:
                        val = f.get("value", "")
                        field_desc = f.get("field", "").lower()
                        if not val or not page_data:
                            continue
                        for inp in page_data.get("inputs", []):
                            if field_desc in (inp.get("label", "") + inp.get("placeholder", "")).lower():
                                try:
                                    page.locator(inp["selector"]).fill(val)
                                    attempt_result["filled"] = attempt_result.get("filled", 0) + 1
                                except Exception:
                                    pass
                                break
                if visual["advice"]:
                    print(f"      👁️ AI advice: {visual['advice'][:200]}")
                if visual["errors"]:
                    print(f"      👁️ AI saw errors: {visual['errors'][:3]}")

        result["attempts"].append(attempt_result)
        wait(2, 4)

    # All retries exhausted
    if result["status"] == "pending":
        result["status"] = "failed_all_retries"
    save_learned(learned)
    return result


def _try_cloudscraper(url: str) -> list[dict]:
    """Try cloudscraper to bypass Cloudflare. Returns Playwright-compatible cookies or []."""
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper(browser="chrome", interpreter="js2py", delay=5)
        resp = scraper.get(url, timeout=30)
        if resp.status_code < 400 and "just a moment" not in resp.text.lower():
            domain = re.sub(r'https?://(www\.)?', '', url).split('/')[0]
            return [{"name": k, "value": v, "domain": domain, "path": "/"}
                    for k, v in resp.cookies.items()]
    except Exception:
        pass
    return []


def run_applications(jobs: list[dict], dry_run: bool = True, max_apps: int = 10, db=None) -> list[dict]:
    """Apply to multiple jobs with self-learning and stealth anti-detection."""
    profile = load_profile()
    learned = load_learned()
    results = []

    # Track same-session failures per domain — skip after 2 failures on same domain
    session_failures = {}  # domain -> failure count

    # Known CAPTCHA-free ATS domains — skip all stealth probing
    CAPTCHA_FREE_DOMAINS = {"jobs.lever.co", "lever.co", "boards.greenhouse.io",
                            "jobs.ashbyhq.com", "apply.workable.com"}

    # Log available stealth tools
    tools = list_available_tools()
    available = [t["name"] for t in tools if t["available"]]
    print(f"  🛡️ Stealth tools available: {', '.join(available)}")

    context = cloakbrowser.launch_context(headless=True)
    # Inject Indeed cookies for authenticated apply
    indeed_cookies = load_indeed_cookies()
    if indeed_cookies:
        context.add_cookies(indeed_cookies)
        print(f"  🍪 Loaded {len(indeed_cookies)} Indeed cookies")

    # Rate limiting
    from cookie_agent import can_apply, record_apply, human_delay
    page = context.new_page()
    applied = 0

    for job in jobs:
        if applied >= max_apps:
            break
        url = job.get("url", "")
        domain = re.sub(r'https?://(www\.)?', '', url).split('/')[0]

        # Skip domains that failed 2+ times this session (same form = same error)
        if session_failures.get(domain, 0) >= 2:
            print(f"\n  ⏭️ Skipping {domain} — failed {session_failures[domain]}x this session")
            results.append({"url": url, "title": job.get("title", ""),
                            "company": job.get("company", ""), "status": "domain_skip"})
            continue

        # Rate limit check — avoid getting restricted
        site_key = job.get("ats_type", "default")
        if not can_apply(site_key):
            print(f"\n  ⏸️ Rate limit reached for {site_key} — skipping")
            continue

        print(f"\n  {'='*50}")
        print(f"  {job.get('title','?')} @ {job.get('company','?')}")

        # SKIP STEALTH for known CAPTCHA-free ATS platforms
        is_captcha_free = any(d in url for d in CAPTCHA_FREE_DOMAINS)

        if is_captcha_free:
            print(f"    🟢 CAPTCHA-free ATS — direct access (no stealth needed)")
        else:
            # STEALTH PRE-CHECK: probe the URL with curl_cffi first
            try:
                probe = fetch_curl_cffi(url)
                if probe.success and "captcha" not in probe.html.lower() and "just a moment" not in probe.html.lower():
                    print(f"    🟢 Direct access OK ({probe.elapsed:.1f}s)")
                else:
                    # Try cloudscraper
                    cf_cookies = _try_cloudscraper(url)
                    if cf_cookies:
                        context.add_cookies(cf_cookies)
                        print(f"    🟢 cloudscraper bypassed CF — injected {len(cf_cookies)} cookies")
                    else:
                        # All stealth tools — but graceful failure
                        print(f"    🔴 Site protected — trying stealth tools...")
                        stealth_result = stealth_fetch(url, tools=["sarperavci", "seleniumbase_uc", "camoufox", "cf_bypass"], headless=True)
                        if stealth_result.success and stealth_result.cookies:
                            pw_cookies = []
                            for c in stealth_result.cookies:
                                if isinstance(c, dict) and c.get("name") and c.get("value"):
                                    pw_cookies.append({
                                        "name": c["name"], "value": c["value"],
                                        "domain": c.get("domain", domain),
                                        "path": c.get("path", "/"),
                                    })
                            if pw_cookies:
                                context.add_cookies(pw_cookies)
                                print(f"    🍪 Injected {len(pw_cookies)} cookies from {stealth_result.tool}")
                        elif stealth_result.success:
                            print(f"    🟡 {stealth_result.tool} got page but no cookies to inject")
                        else:
                            # GRACEFUL SKIP — don't crash CI
                            print(f"    ⏭️ All stealth tools failed — skipping: {stealth_result.error[:80]}")
                            results.append({"url": url, "title": job.get("title", ""),
                                            "company": job.get("company", ""), "status": "stealth_failed"})
                            continue
            except Exception as e:
                print(f"    ⏭️ Stealth probe crashed — skipping: {str(e)[:80]}")
                results.append({"url": url, "title": job.get("title", ""),
                                "company": job.get("company", ""), "status": "stealth_crashed"})
                continue

        r = apply_to_job(page, profile, job, learned, dry_run, db=db)
        results.append(r)
        if r["status"] in ("submitted", "dry_run"):
            applied += 1
            record_apply(site_key)
            human_delay(site_key)  # Random wait to look human
        else:
            # Track domain failures to skip after 2
            if r["status"] in ("failed_all_retries", "captcha_blocked"):
                session_failures[domain] = session_failures.get(domain, 0) + 1
            wait(1, 2)

    context.close()

    save_learned(learned)
    ok = sum(1 for r in results if r["status"] in ("submitted", "dry_run"))
    print(f"\n  📊 {ok}/{len(results)} applied | Learned selectors for {len(learned.get('winning_selectors', {}))} domains")
    return results
