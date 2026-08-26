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
try:
    import cloakbrowser
except ImportError:
    cloakbrowser = None
from src.stealth_toolkit import stealth_fetch, fetch_curl_cffi, list_available_tools, StealthResult

PROFILE_PATH = Path(__file__).parent.parent / "config" / "profile.json"
RESUME_PATH = Path(__file__).parent.parent / "resume.pdf"
SCREENSHOTS = Path(__file__).parent.parent / "screenshots"
LEARNED_FILE = Path(__file__).parent.parent / "data" / "learned.json"
INDEED_COOKIES_FILE = Path(__file__).parent.parent / "data" / "indeed_cookies.json"
MAX_RETRIES = 2


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
    # Work authorization
    "authorized": "Yes", "legally authorized": "Yes", "eligible to work": "Yes", "work in the u": "Yes",
    "sponsorship": "No", "require sponsor": "No", "visa sponsor": "No", "need sponsorship": "No",
    "currently sponsoring": "No", "will you now or in the future": "No",
    # Location / relocation
    "relocate": "No", "willing to relocate": "No",
    "country": "United States", "state": "Colorado",
    # Availability / timing
    "start": "Immediately", "when can you": "Immediately", "available": "Immediately",
    "notice period": "2 weeks",
    # Compensation
    "salary": "150000", "compensation": "150000", "expected pay": "150000",
    "hourly": "75", "rate": "75", "desired salary": "150000",
    # Source
    "hear about": "Online Job Board", "how did you": "Online Job Board", "source": "Job Board",
    "referred by": "Online Job Board", "how did you find": "Online Job Board",
    # DEI / sensitive — decline to avoid any blocking
    "gender": "Decline to state", "pronoun": "Prefer not to answer",
    "race": "Decline to state", "ethnicity": "Decline to state", "demographic": "Decline to state",
    "veteran": "I am not a protected veteran", "disability": "I do not wish to answer",
    "sexual orientation": "Decline to state",
    # Language
    "language": "English", "primary language": "English", "english proficiency": "Professional",
    # Misc
    "background check": "Yes", "consent": "Yes", "agree": "Yes",
    "remote": "Yes", "work remotely": "Yes", "open to remote": "Yes",
    "employment type": "Contract", "contract type": "Corp-to-Corp (C2C)",
    "years of experience": "10+",
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
                # Try clicking the Attach/Upload button to trigger file chooser
                try:
                    with page.expect_file_chooser(timeout=5000) as fc:
                        # Greenhouse uses "Attach" button next to hidden file input
                        attach_btn = page.locator(f'button:near(#{fi.get("id", "resume")}):has-text("Attach"), button:has-text("Attach"), button:has-text("Upload"), label[for="{fi.get("id", "")}"]').first
                        if attach_btn.is_visible(timeout=1000):
                            attach_btn.click()
                        else:
                            page.click('text=/attach|upload|resume|cv/i')
                    fc.value.set_files(str(RESUME_PATH))
                    filled.append(("resume", "file_chooser"))
                    wait(1, 2)
                except Exception:
                    # Last resort: force set via JavaScript
                    try:
                        sel = fi["selector"] or 'input[type="file"]'
                        page.locator(sel).set_input_files(str(RESUME_PATH), timeout=3000)
                        filled.append(("resume", "force_set"))
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
        else:
            # ANY other textarea question — use Gemini AI to generate answer
            try:
                from src.ai_fallback import ask_ai_about_field
                ai_answer = ask_ai_about_field(label, "textarea")
                if ai_answer:
                    page.locator(sel).fill(ai_answer)
                    filled.append(("ai:" + label[:30], sel))
            except Exception:
                # Fallback: generic answer
                try:
                    page.locator(sel).fill(
                        "10+ years of Java/Spring Boot development. "
                        "Expert in microservices, Kafka, Kubernetes, AWS. "
                        "Available immediately for C2C contract. Green Card holder."
                    )
                    filled.append(("generic_answer", sel))
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

def _try_auto_captcha_solve(page, captured_sitekey: str = "") -> bool:
    """Solve any CAPTCHA using a chain of free solvers. Tries each until one succeeds.
    
    Chain (in order of reliability for job applications):
    1. NopeCHA — 100 free/day, best for reCAPTCHA + hCaptcha
    2. playwright-recaptcha — FREE unlimited, audio challenge (reCAPTCHA v2 only)
    3. OhMyCaptcha (self-hosted) — uses Gemini AI, unlimited if key is set
    4. Browser score fallback — rely on CloakBrowser stealth + human simulation
    
    Each run uses ~25 CAPTCHAs (50 jobs, ~50% have CAPTCHA).
    4 runs/day = ~100 CAPTCHAs = exactly NopeCHA free tier.
    If NopeCHA runs out → playwright-recaptcha handles the rest (unlimited).
    """
    import os
    
    # First: check if there's even a CAPTCHA on this page
    has_captcha = False
    try:
        has_captcha = page.evaluate("""() => {
            return !!(
                document.querySelector('.g-recaptcha, .h-captcha, .cf-turnstile, [data-captcha]') ||
                document.querySelector('script[src*="recaptcha"], script[src*="hcaptcha"], script[src*="turnstile"]') ||
                document.querySelector('iframe[src*="recaptcha"], iframe[src*="hcaptcha"]')
            );
        }""")
    except Exception:
        pass
    
    if not has_captcha:
        return True  # no CAPTCHA, proceed to submit
    
    print(f"      🔓 CAPTCHA detected — trying solver chain...")
    
    # === SOLVER 1: NopeCHA (auto-captcha library) ===
    nopecha_key = os.environ.get("NOPECHA_API_KEY", "")
    if nopecha_key:
        try:
            from auto_captcha_solver import CaptchaSolver
            solver = CaptchaSolver(api_key=nopecha_key)
            captchas = solver.detect(page)
            if captchas:
                result = solver.solve(
                    captcha_type=captchas[0]["type"],
                    sitekey=captchas[0].get("sitekey", ""),
                    url=page.url,
                )
                if result.success:
                    solver.inject(page, captchas[0]["type"], result.token)
                    print(f"      ✅ Solved via NopeCHA ({captchas[0]['type']})")
                    return True
                else:
                    print(f"      ⚠️ NopeCHA failed — trying next solver...")
        except ImportError:
            pass
        except Exception as e:
            if "limit" in str(e).lower() or "quota" in str(e).lower() or "429" in str(e):
                print(f"      ⚠️ NopeCHA daily limit reached — trying next solver...")
            else:
                print(f"      ⚠️ NopeCHA error: {str(e)[:50]} — trying next...")
    
    # === SOLVER 2: playwright-recaptcha (FREE, unlimited, audio-based) ===
    try:
        from playwright_recaptcha import recaptchav2
        with recaptchav2.SyncSolver(page) as solver:
            token = solver.solve_recaptcha(wait=True)
            if token and len(token) > 20:
                print(f"      ✅ Solved via playwright-recaptcha (audio)")
                return True
    except Exception as e:
        err = str(e).lower()
        if "rate limit" in err:
            print(f"      ⚠️ Audio solver rate-limited — trying next...")
        else:
            pass  # not a visible reCAPTCHA v2, try next
    
    # === SOLVER 3: OhMyCaptcha (self-hosted, needs Gemini key) ===
    omc_url = os.environ.get("OHMYCAPTCHA_URL", "")
    if omc_url:
        try:
            from src.page_doctor import detect_captcha_type, solve_via_ohmycaptcha
            captcha_info = detect_captcha_type(page)
            if captcha_info:
                if solve_via_ohmycaptcha(page, captcha_info):
                    print(f"      ✅ Solved via OhMyCaptcha")
                    return True
        except Exception:
            pass
    
    # === SOLVER 3.5: hCaptcha via token-based solving service (CapSolver/2Captcha) ===
    # Only triggers when hCaptcha is ACTIVELY BLOCKING (challenge iframe visible OR form requires token)
    try:
        hcaptcha_blocking = page.evaluate("""() => {
            // Must have a sitekey element (confirms this IS hCaptcha, not something else)
            const hcDiv = document.querySelector('.h-captcha[data-sitekey], [data-hcaptcha-sitekey]');
            if (!hcDiv) return false;
            
            // Check if challenge iframe is loaded (means it triggered)
            const challengeIframe = document.querySelector('iframe[src*="hcaptcha.com/challenge"]');
            if (challengeIframe) return true;
            
            // Check if response textarea is empty (captcha not yet solved)
            const ta = document.querySelector('[name="h-captcha-response"]');
            if (ta && ta.value && ta.value.length > 20) return false;  // already solved
            
            // hCaptcha widget exists and is unsolved — it WILL block submission
            return true;
        }""")
        if hcaptcha_blocking:
            from src.hcaptcha_solver import solve_hcaptcha
            if solve_hcaptcha(page):
                print(f"      ✅ Solved hCaptcha via token service")
                return True
            else:
                print(f"      ⚠️ hCaptcha token solver failed — trying next...")
    except ImportError:
        pass
    except Exception as e:
        print(f"      ⚠️ hCaptcha solver error: {str(e)[:50]} — trying next...")

    # === SOLVER 4: reCAPTCHA Enterprise — execute token directly ===
    try:
        from src.page_doctor import solve_recaptcha_enterprise
        if solve_recaptcha_enterprise(page, page.url, override_sitekey=captured_sitekey):
            return True
        else:
            # reCAPTCHA Enterprise explicitly failed — don't proceed blindly
            print(f"      ⚠️ reCAPTCHA Enterprise unsolvable — submission will likely fail")
            return False
    except Exception:
        pass
    
    # === FALLBACK: no known CAPTCHA detected, proceed with submission ===
    print(f"      🔓 No blocking CAPTCHA detected — proceeding")
    return True


def _fill_remaining_required(page, profile: dict) -> int:
    """Dynamic adaptation — find and fill ANY remaining empty required fields.
    
    This catches:
    - New questions added after our last code update
    - Different company's custom questions we haven't seen before
    - Page layout changes (fields moved, renamed, added)
    - Multi-step forms where new fields appeared after previous fills
    
    Strategy:
    1. Find all required inputs/comboboxes that are still empty
    2. Match by label/name/placeholder to profile or known answers
    3. Use smart defaults for common patterns
    """
    filled = 0
    
    # Smart answers for common job application patterns
    SMART_ANSWERS = {
        # Work authorization
        "authorized": "Yes", "legally authorized": "Yes", "eligible": "Yes", "permanent resident": "Yes",
        "right to work": "Yes", "work permit": "Yes", "employment eligibility": "Yes",
        # Sponsorship  
        "sponsorship": "No", "visa": "No", "require sponsor": "No", "immigration": "No",
        "citizen": "No", "us citizen": "No", "citizenship": "No", "u.s. citizen": "No",
        # Relocation
        "relocate": "No", "willing to relocate": "No", "open to relocation": "No",
        # Availability
        "start": "Immediately", "when can you": "Immediately", "available": "Immediately",
        "notice period": "Immediately", "earliest start": "Immediately",
        # Compensation
        "salary": "150000", "expected salary": "150000", "desired salary": "150000",
        "compensation": "150000", "hourly": "75", "rate": "75",
        # Source
        "hear about": "Other", "how did you": "Other", "source": "Other",
        "where did you find": "Other", "referred": "No",
        "learn about": "Other", "first learn": "Other",
        # Background
        "background check": "Yes", "consent": "Yes", "agree": "Yes",
        "acknowledge": "Yes", "terms": "Yes", "privacy": "Yes",
        # Demographics (use real answers — works better than "Decline" on most forms)
        "gender": "Male", "gender identity": "Male", "sex": "Male",
        "identify your race": "White", "race": "White", "ethnicity": "White",
        "veteran": "I am not a protected veteran", "military": "No",
        "disability": "I do not want to answer", "i do not wish": "I do not want to answer",
        "don't wish to answer": "I do not want to answer",
        "hispanic": "No", "latino": "No", "latina": "No",
        "transgender": "No",
        "sexual orientation": "Heterosexual", "orientation": "Heterosexual",
        # Planning/state questions
        "planning to work": "Yes", "plan to work": "Yes", "work from these states": "Yes",
        "intend to work": "Yes",
        # Decline wording variants (different companies use different text)
        "decline to self": "Decline To Self Identify", "self-identify": "Decline To Self Identify",
        # Employment
        "previously employed": "No", "worked here before": "No", "former employee": "No",
        "worked for": "No", "ever worked": "No", "recording": "Yes", "interview recording": "Yes",
        # Experience
        "years of experience": "10", "experience": "10",
        # Education
        "degree": "Bachelor", "highest education": "Bachelor",
        # Remote
        "remote": "Yes", "work remotely": "Yes", "hybrid": "Yes",
        # Clearance
        "security clearance": "No", "clearance": "No",
        # Non-compete
        "non-compete": "No", "non compete": "No", "restrictive covenant": "No",
        # Country/Location
        "country": "United States", "state": profile.get("state", "CO"),
        # EU/citizenship questions
        "eu citizen": "No", "european union": "No", "citizen": "No",
        "right to work": "Yes", "legal right": "Yes", "legally authorized": "Yes",
        "work permit": "No", "visa": "No",
        "province": profile.get("state", "CO"),
        # Pronoun
        "pronoun": "He/Him",
        # Languages (DataDog, international companies)
        "language": "English", "languages you speak": "English", "fluent": "English",
        "primary language": "English",
        # Work type
        "employment type": "Contract", "work type": "Contract", "contract": "Yes",
        "corp to corp": "Yes", "c2c": "Yes", "w2": "No",
        # Travel
        "travel": "No", "willing to travel": "No", "business travel": "No",
        # Drug test
        "drug test": "Yes", "drug screen": "Yes",
        # Age
        "18 years": "Yes", "over 18": "Yes", "at least 18": "Yes",
        # Shift
        "shift": "Day", "work schedule": "Regular",
    }
    
    try:
        # 1. Find empty required TEXT inputs (both aria-required and HTML5 required)
        all_inputs = page.locator('input[aria-required="true"]:not([type="hidden"]):not([type="file"]):not([type="checkbox"]):not([type="radio"]), input[required]:not([type="hidden"]):not([type="file"]):not([type="checkbox"]):not([type="radio"])').all()
        
        for inp in all_inputs:
            try:
                val = inp.input_value(timeout=500)
                if val and val.strip():
                    continue  # already filled
                
                # Get label
                label = ""
                label_id = inp.get_attribute("aria-labelledby") or ""
                if label_id:
                    try:
                        label = page.locator(f"#{label_id}").first.inner_text(timeout=300)
                    except Exception:
                        pass
                if not label:
                    label = inp.get_attribute("aria-label") or inp.get_attribute("placeholder") or inp.get_attribute("name") or ""
                
                if not label:
                    continue
                
                label_lower = label.lower()
                
                # Try profile fields first
                profile_map = {
                    "first name": profile.get("first_name", ""),
                    "last name": profile.get("last_name", ""),
                    "email": profile.get("email", ""),
                    "phone": profile.get("phone", ""),
                    "linkedin": profile.get("linkedin", ""),
                    "github": profile.get("github", ""),
                    "city": profile.get("city", ""),
                    "zip": profile.get("zip", ""),
                    "address": profile.get("location", ""),
                    "location": profile.get("location", ""),
                    "company": "",  # leave empty (not currently employed)
                    "title": profile.get("title", ""),
                    "preferred name": profile.get("first_name", ""),
                    "name": profile.get("name", ""),
                    "website": profile.get("linkedin", ""),
                    "portfolio": profile.get("github", ""),
                }
                
                value = None
                for key, val in profile_map.items():
                    if key in label_lower and val:
                        value = val
                        break
                
                # Try smart answers
                if not value:
                    for key, ans in SMART_ANSWERS.items():
                        if key in label_lower:
                            value = ans
                            break
                
                if value:
                    inp.fill(str(value))
                    filled += 1
                    
            except Exception:
                continue
        
        # 2. Find empty required COMBOBOXES (React Select style)
        # Use a loop with re-scan to catch dynamically appearing fields (e.g., "race" after Hispanic=No)
        max_combo_passes = 3  # Max re-scan attempts for dynamic fields
        for combo_pass in range(max_combo_passes):
            comboboxes = page.locator('input[role="combobox"][aria-required="true"]').all()
            filled_this_pass = 0
            
            for combo in comboboxes:
                try:
                    # Check if already has value
                    parent_ctrl = combo.locator("xpath=ancestor::div[contains(@class,'select__control')]")
                    try:
                        single_val = parent_ctrl.locator('[class*="singleValue"], [class*="single-value"]')
                        if single_val.count() > 0:
                            text = single_val.first.inner_text(timeout=300)
                            if text and text.strip() and text.strip() != "Select...":
                                continue  # already filled
                    except Exception:
                        pass
                    
                    # Get label
                    label = ""
                    label_id = combo.get_attribute("aria-labelledby") or ""
                    if label_id:
                        try:
                            label = page.locator(f"#{label_id}").first.inner_text(timeout=300)
                        except Exception:
                            pass
                    
                    if not label:
                        continue
                    
                    label_lower = label.lower()
                    
                    # Find answer from smart answers
                    answer = None
                    for key, ans in SMART_ANSWERS.items():
                        if key in label_lower:
                            answer = ans
                            break
                    
                    # Check learned answers from previous AI calls
                    if not answer:
                        learned = load_learned()
                        learned_combos = learned.get("combobox_answers", {})
                        if label_lower in learned_combos:
                            answer = learned_combos[label_lower]
                    
                    # AI fallback — ask Gemini if still no answer
                    if not answer:
                        try:
                            from src.ai_fallback import ask_ai_about_field
                            # First open dropdown to get options
                            combo.click()
                            time.sleep(0.2)
                            page.keyboard.press("ArrowDown")
                            time.sleep(0.3)
                            opts = page.locator('[role="option"]')
                            opt_texts = [opts.nth(i).inner_text(timeout=300).strip() for i in range(min(opts.count(), 15))]
                            page.keyboard.press("Escape")
                            time.sleep(0.1)
                            
                            if opt_texts:
                                ai_answer = ask_ai_about_field(label, "combobox", opt_texts)
                                if ai_answer and ai_answer.upper() != "SKIP":
                                    answer = ai_answer
                                    # Save for next time — no API call needed
                                    learned.setdefault("combobox_answers", {})[label_lower] = answer
                                    save_learned(learned)
                        except Exception:
                            pass
                    
                    if not answer:
                        continue
                    
                    # React Select: click → ArrowDown (opens menu) → type (filters) → exact match select
                    combo.click()
                    time.sleep(0.2)
                    page.keyboard.press("ArrowDown")  # Opens the dropdown
                    time.sleep(0.3)
                    page.keyboard.type(answer, delay=30)  # Type to filter options (30ms = fast but triggers React)
                    time.sleep(0.3)
                    
                    # Try EXACT match first (fixes Male→Female bug)
                    # Use Playwright filter for performance instead of looping all options
                    options = page.locator('[role="option"]')
                    option_count = options.count()
                    exact_found = False
                    
                    if option_count > 0:
                        # Fast path: try to find exact text match using locator filter
                        exact_option = options.filter(has_text=answer)
                        if exact_option.count() > 0:
                            # Verify it's truly exact (filter is substring match)
                            for i in range(exact_option.count()):
                                opt_text = exact_option.nth(i).inner_text(timeout=500).strip()
                                if opt_text.lower() == answer.lower():
                                    exact_option.nth(i).click()
                                    exact_found = True
                                    break
                        
                        if not exact_found:
                            # No exact match — pick first visible option
                            page.keyboard.press("Enter")
                        
                        filled += 1
                        filled_this_pass += 1
                        time.sleep(0.2)
                    else:
                        # No options from typing — try opening menu and selecting first
                        page.keyboard.press("Escape")
                        time.sleep(0.15)
                        combo.click()
                        time.sleep(0.2)
                        page.keyboard.press("ArrowDown")
                        time.sleep(0.3)
                        page.keyboard.press("Enter")  # Select first available option
                        filled += 1
                        filled_this_pass += 1
                        time.sleep(0.2)
                            
                except Exception:
                    try:
                        page.keyboard.press("Escape")
                    except Exception:
                        pass
                    continue
            
            # If nothing was filled this pass, no new fields appeared — stop re-scanning
            if filled_this_pass == 0:
                break
            # Brief wait for any dynamic fields to render after selections
            time.sleep(0.3)
        
        # 3. Handle required checkboxes (consent, agree, terms)
        checkboxes = page.locator('input[type="checkbox"][required], input[type="checkbox"][aria-required="true"]').all()
        for cb in checkboxes:
            try:
                if not cb.is_checked():
                    # Get label to check if it's safe to check
                    label = ""
                    try:
                        parent = cb.locator("xpath=ancestor::label")
                        label = parent.inner_text(timeout=300).lower()
                    except Exception:
                        pass
                    # Skip non-compete/exclusivity
                    if any(skip in label for skip in ["non-compete", "noncompete", "exclusiv"]):
                        continue
                    cb.check()
                    filled += 1
            except Exception:
                continue

        # 4. Handle required RADIO BUTTONS (authorization, sponsorship, relocation, etc.)
        try:
            # Find fieldsets/groups with required radio buttons that have NO selection
            radio_groups = page.locator('fieldset:has(input[type="radio"])').all()
            for group in radio_groups:
                try:
                    # Check if any radio in this group is already checked
                    checked = group.locator('input[type="radio"]:checked')
                    if checked.count() > 0:
                        continue  # already answered

                    # Get the question (legend or label)
                    question = ""
                    try:
                        question = group.locator("legend").first.inner_text(timeout=300)
                    except Exception:
                        try:
                            question = group.locator("label").first.inner_text(timeout=300)
                        except Exception:
                            pass

                    if not question:
                        continue

                    q_lower = question.lower()

                    # Determine answer based on question
                    answer = None
                    # Yes answers
                    yes_patterns = ["authorized", "legally", "eligible", "right to work",
                                    "background check", "consent", "18 years", "over 18",
                                    "drug test", "agree", "acknowledge"]
                    # No answers
                    no_patterns = ["sponsorship", "visa", "require sponsor", "relocate",
                                   "non-compete", "previously employed", "worked here",
                                   "clearance", "disability"]

                    if any(p in q_lower for p in yes_patterns):
                        answer = "yes"
                    elif any(p in q_lower for p in no_patterns):
                        answer = "no"
                    
                    if not answer:
                        continue

                    # Click the matching radio button
                    radios = group.locator('input[type="radio"]').all()
                    for radio in radios:
                        try:
                            label = radio.locator("xpath=following-sibling::label | ancestor::label").first.inner_text(timeout=300).lower()
                        except Exception:
                            label = radio.get_attribute("value") or ""
                            label = label.lower()

                        if answer in label:
                            radio.click()
                            filled += 1
                            break
                    else:
                        # Fallback: if no label matches, click first radio for "yes", second for "no"
                        if len(radios) >= 2:
                            idx = 0 if answer == "yes" else 1
                            radios[idx].click()
                            filled += 1
                except Exception:
                    continue
        except Exception:
            pass

        # 5. Handle old-style <select required> that are still empty
        old_selects = page.locator('select:visible').all()  # Fill ALL visible selects (not just required — Greenhouse validates via JS)
        for sel in old_selects:
            try:
                current_val = sel.input_value(timeout=500)
                if current_val:
                    continue  # already has a value selected
                
                # Get label
                label = ""
                sel_id = sel.get_attribute("id") or ""
                if sel_id:
                    try:
                        label = page.locator(f'label[for="{sel_id}"]').first.inner_text(timeout=300)
                    except Exception:
                        pass
                if not label:
                    label = sel.get_attribute("aria-label") or sel.get_attribute("name") or ""
                
                label_lower = label.lower()
                
                # Try to find matching answer in options
                answer = None
                for key, ans in SMART_ANSWERS.items():
                    if key in label_lower:
                        answer = ans
                        break
                
                if answer:
                    # Try to select option containing the answer
                    options = sel.locator('option').all()
                    for opt in options:
                        try:
                            opt_text = opt.inner_text(timeout=200)
                            if answer.lower() in opt_text.lower():
                                sel.select_option(label=opt_text)
                                filled += 1
                                break
                        except Exception:
                            continue
                else:
                    # No matching answer — select first non-empty, non-placeholder option
                    options = sel.locator('option').all()
                    for opt in options[1:]:  # skip first (usually "Select..." or empty)
                        try:
                            val = opt.get_attribute("value")
                            opt_text = opt.inner_text(timeout=200).strip()
                            if val and opt_text and opt_text.lower() not in ("select", "select...", "choose", "-- select --", ""):
                                sel.select_option(value=val)
                                filled += 1
                                break
                        except Exception:
                            continue
            except Exception:
                continue
                
    except Exception:
        pass

    # 5. ARIA-INVALID: After submit failure, ATS marks invalid fields with aria-invalid="true"
    # These fields may NOT have required/aria-required but are still blocking submit
    try:
        invalid_inputs = page.locator('input[aria-invalid="true"]:visible, select[aria-invalid="true"]:visible, textarea[aria-invalid="true"]:visible').all()
        for inp in invalid_inputs:
            try:
                tag = inp.evaluate("el => el.tagName.toLowerCase()")
                current_val = inp.input_value(timeout=500) if tag != "select" else ""
                if current_val and current_val.strip():
                    continue  # has value but still invalid (format issue) — skip

                # Get label
                label = ""
                inp_id = inp.get_attribute("id") or ""
                if inp_id:
                    try:
                        label = page.locator(f'label[for="{inp_id}"]').first.inner_text(timeout=300)
                    except Exception:
                        pass
                if not label:
                    label = inp.get_attribute("aria-label") or inp.get_attribute("placeholder") or inp.get_attribute("name") or ""

                label_lower = label.lower()
                if not label_lower:
                    continue

                # Try profile mapping then smart answers
                value = None
                profile_map = {
                    "first name": profile.get("first_name", ""),
                    "last name": profile.get("last_name", ""),
                    "email": profile.get("email", ""),
                    "phone": profile.get("phone", ""),
                    "linkedin": profile.get("linkedin", ""),
                    "city": profile.get("city", ""),
                    "zip": profile.get("zip", ""),
                    "location": profile.get("location", ""),
                    "name": profile.get("name", ""),
                }
                for key, val in profile_map.items():
                    if key in label_lower and val:
                        value = val
                        break

                if not value:
                    for key, ans in SMART_ANSWERS.items():
                        if key in label_lower:
                            value = ans
                            break

                if value:
                    if tag == "select":
                        # Try select option
                        options = inp.locator("option").all()
                        for opt in options[1:]:
                            try:
                                opt_text = opt.inner_text(timeout=200)
                                if value.lower() in opt_text.lower():
                                    inp.select_option(label=opt_text)
                                    filled += 1
                                    break
                            except Exception:
                                continue
                    else:
                        inp.fill(str(value))
                        filled += 1
            except Exception:
                continue
    except Exception:
        pass

    return filled


def submit_and_verify(page, page_data, original_url) -> dict:
    """Find submit button, click it, verify success."""
    submit_texts = ["submit application", "submit", "apply now", "apply", "send application", "send", "complete"]
    skip_texts = ["linkedin", "google", "facebook", "twitter", "sign in", "log in", "dismiss"]

    # Intercept POST/PUT responses — a 2xx with no DOM errors is ground-truth success
    post_responses: list[dict] = []
    def _on_response(response):
        if response.request.method in ("POST", "PUT") and 200 <= response.status < 400:
            post_responses.append({"url": response.url, "status": response.status})
    page.on("response", _on_response)

    for btn in page_data["buttons"]:
        btn_lower = btn["text"].lower()
        if any(s in btn_lower for s in skip_texts):
            continue
        for st in submit_texts:
            if st in btn_lower:
                try:
                    post_responses.clear()
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

                    # 1. URL or page text success signal
                    success_signals = ["thank", "success", "received", "submitted", "confirmation", "applied", "complete"]
                    # Exclude pages that ask for security/verification code — those aren't real success
                    is_verification_page = "security" in text or "verification code" in text or "paste this code" in text
                    if not is_verification_page and (any(s in url for s in success_signals) or any(s in text for s in success_signals)):
                        return {"submitted": True, "method": btn["text"]}

                    # 2. Specific error phrases only — never match "a required field" or "indicates required"
                    error_signals = ["this field is required", "please fill", "is invalid",
                                     "cannot be blank", "must be completed"]
                    errors = [s for s in error_signals if s in text]
                    # Visible error ELEMENTS — but exclude generic banners/labels (only field-level errors)
                    try:
                        field_errors = page.locator(
                            '[class*="field-error"]:visible, [class*="FieldError"]:visible, '
                            '[aria-invalid="true"]:visible, [class*="validation-error"]:visible, '
                            'span.error:visible, p.error:visible'
                        ).count()
                        if field_errors > 0:
                            errors.append(f"{field_errors}_field_errors")
                    except Exception:
                        pass
                    if errors:
                        return {"submitted": False, "reason": f"Form errors: {errors}"}

                    # 3. URL changed = possible success (Greenhouse redirects on submit)
                    if url != original_url.lower().rstrip("/"):
                        # BUT: check if the new page asks for a security code (email verification)
                        # If so, it's NOT submitted yet — needs code entry
                        if "security" in text or "verification" in text or "code" in text:
                            return {"submitted": False, "reason": "email_verification_required"}
                        return {"submitted": True, "method": "url_changed"}

                    # 4. Intercepted a successful POST and no DOM errors visible
                    if post_responses:
                        return {"submitted": True, "method": "post_intercepted"}

                    return {"submitted": False, "reason": "No success signal after submit"}
                except Exception as e:
                    return {"submitted": False, "reason": str(e)[:200]}

    return {"submitted": False, "reason": "No submit button found"}


# ─── MAIN: The self-learning retry loop ───

def apply_to_job(page, profile, job, learned, dry_run=False, db=None, site_needs_cf_solve=False) -> dict:
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
            if "boards.greenhouse.io" in apply_url and "job-boards" not in apply_url and "#app" not in apply_url:
                apply_url += "#app"
            # For job-boards.greenhouse.io/company/jobs/ID — use embed URL (avoids redirect + iframe)
            # Embed URL gives direct form access with all fields visible immediately
            import re as _re
            _gh_embed_match = _re.search(r'job-boards\.greenhouse\.io/([^/]+)/jobs/(\d+)', apply_url)
            if _gh_embed_match and "/embed/" not in apply_url:
                _gh_embed_company = _gh_embed_match.group(1)
                _gh_embed_id = _gh_embed_match.group(2)
                embed_url = f"https://job-boards.greenhouse.io/embed/job_app?for={_gh_embed_company}&token={_gh_embed_id}"
                print(f"      📋 Using Greenhouse embed URL (direct form)")
                apply_url = embed_url
            if "ashbyhq.com" in apply_url and not apply_url.endswith("/application"):
                apply_url += "/application"
            
            # For company-hosted Greenhouse jobs (e.g., thoughtworks.com/careers/jobs/XXX?gh_jid=XXX)
            # Redirect directly to the Greenhouse job-boards apply page
            if "gh_jid=" in apply_url and "greenhouse.io" not in apply_url:
                import re as _re
                gh_match = _re.search(r'gh_jid=(\d+)', apply_url)
                if gh_match:
                    # Extract company from the portal scanner (stored in job dict)
                    gh_company = job.get("company", "").lower().replace(" ", "")
                    apply_url = f"https://job-boards.greenhouse.io/{gh_company}/jobs/{gh_match.group(1)}"
                    print(f"      📎 Redirected to Greenhouse: {apply_url}")

            # Set up network listener to capture reCAPTCHA sitekey from request URLs
            _captured_recaptcha_sitekey = []
            def _capture_recaptcha_url(request):
                if 'recaptcha' in request.url:
                    import re as _re2
                    m = _re2.search(r'render=([^&]+)', request.url)
                    if m and m.group(1) != 'explicit':
                        _captured_recaptcha_sitekey.append(m.group(1))
                    m2 = _re2.search(r'[?&]k=([^&]+)', request.url)
                    if m2:
                        _captured_recaptcha_sitekey.append(m2.group(1))
            try:
                page.on("request", _capture_recaptcha_url)
            except Exception:
                pass

            page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
            # Handle Cloudflare "Verify you are human" challenge (if present)
            try:
                from src.page_doctor import solve_cf_checkbox
                # If pre-check told us site is CF-protected, try harder (more attempts)
                cf_max = 3 if site_needs_cf_solve else 2
                cf_passed = solve_cf_checkbox(page, max_attempts=cf_max)
                if not cf_passed and site_needs_cf_solve:
                    # CF challenge couldn't be solved — skip gracefully
                    print(f"      ⏭️ CF challenge unsolvable — skipping")
                    results.append({"url": url, "title": job.get("title", ""),
                                    "company": job.get("company", ""), "status": "cf_blocked"})
                    snap(page, f"cf_blocked_{attempt}")
                    break
            except Exception:
                if site_needs_cf_solve:
                    print(f"      ⏭️ CF solve crashed — skipping")
                    results.append({"url": url, "title": job.get("title", ""),
                                    "company": job.get("company", ""), "status": "cf_crashed"})
                    break
            # Wait for visible form inputs — React apps render after JS executes.
            # Try up to 10 seconds. Fall back to fixed wait if selector never appears.
            try:
                page.wait_for_selector(
                    'input:not([type="hidden"]):not([type="file"]), textarea, select',
                    timeout=10000, state="visible"
                )
            except Exception:
                page.wait_for_timeout(5000)  # fallback: just wait 5s
            wait(0.5, 1.0)

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
                            # Wait for form inputs — React SPAs (Greenhouse) need up to 20s to hydrate
                            try:
                                page.wait_for_selector(
                                    'input:not([type="hidden"]):not([type="file"]), textarea',
                                    timeout=20000, state="visible"
                                )
                            except Exception:
                                page.wait_for_timeout(3000)
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

            # Check if page exists / job is still active
            if page.locator("text=/not found|404|expired|closed|no longer|no longer active|deactivated|removed|unavailable|position.*filled/i").count() > 0:
                result["status"] = "job_closed"
                print(f"      ⏭️ Job expired/closed — skipping")
                snap(page, f"closed_{attempt}")
                break

            # DOCTOR: dismiss popups/cookie banners first
            from src.page_doctor import dismiss_popups, read_errors, fix_errors_and_retry, detect_captcha, detect_multi_step, click_next_button, fix_field_format, solve_turnstile_via_docker, solve_captcha
            dismissed = dismiss_popups(page)
            if dismissed:
                print(f"      Dismissed {dismissed} popups/banners")

            # NEW: Click "Apply" button if form is hidden behind it (Greenhouse embed pattern)
            # This is optional — only triggers when no inputs visible on main page
            try:
                main_inputs = page.locator('input:not([type="hidden"]):not([type="checkbox"])').count()
                if main_inputs < 2:
                    # Try clicking "Apply to this job" link (bottom of page, reveals form)
                    # This is the .view-more-cta link — NOT the "Apply now" header button
                    apply_btns = page.locator('a:has-text("Apply to this job"), .view-more-cta a')
                    if apply_btns.count() > 0:
                        apply_btns.first.click()
                        page.wait_for_timeout(5000)
                    # Reveal hidden Greenhouse iframe (parent often display:none)
                    page.evaluate("""() => {
                        var iframe = document.getElementById('grnhse_iframe');
                        if (iframe) {
                            var el = iframe;
                            while (el && el !== document.body) {
                                el.style.display = 'block';
                                el.style.visibility = 'visible';
                                el.style.height = 'auto';
                                el = el.parentElement;
                            }
                            iframe.style.height = '900px';
                            iframe.style.width = '100%';
                        }
                    }""")
                    page.wait_for_timeout(3000)
            except Exception:
                pass  # Non-fatal — old path continues below

            # For JS-heavy ATS (Greenhouse, Workday, Ashby): wait for form to render
            if any(s in apply_url for s in ["greenhouse", "workday", "myworkday", "ashby"]):
                try:
                    page.wait_for_selector(
                        'input:not([type="hidden"]):not([type="file"]), textarea',
                        timeout=10000, state="visible"
                    )
                except Exception:
                    page.wait_for_timeout(5000)

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

            # HUMAN BEHAVIOR: simulate mouse/scroll before interacting (boosts reCAPTCHA score)
            from src.page_doctor import simulate_human_behavior
            simulate_human_behavior(page)

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

            # Fill Greenhouse/custom React dropdowns BEFORE submit
            from src.page_doctor import fill_greenhouse_custom_fields
            gh_filled = fill_greenhouse_custom_fields(page, profile)
            if gh_filled:
                attempt_result["filled"] += gh_filled
                print(f"      🔽 Filled {gh_filled} custom dropdowns (Greenhouse)")

            # DYNAMIC ADAPTATION: catch any remaining unfilled required fields
            # This handles page changes, new questions, non-standard forms
            dynamic_filled = _fill_remaining_required(page, profile)
            if dynamic_filled:
                attempt_result["filled"] += dynamic_filled
                print(f"      🔄 Dynamic fill: {dynamic_filled} additional fields")

            # Handle reCAPTCHA / CAPTCHA — use auto-captcha solver (NopeCHA, 100 free/day)
            from src.page_doctor import simulate_human_behavior
            simulate_human_behavior(page)
            # Pass any sitekey captured from network requests
            _net_sitekey = _captured_recaptcha_sitekey[0] if _captured_recaptcha_sitekey else ""
            captcha_solved = _try_auto_captcha_solve(page, captured_sitekey=_net_sitekey)

            if not captcha_solved:
                # CAPTCHA unsolvable — don't waste time submitting (will timeout)
                # Mark as captcha_blocked and route to email outreach
                result["status"] = "captcha_blocked"
                result["fields_filled"] = attempt_result["filled"]
                snap(page, f"captcha_blocked_{attempt}")
                print(f"      ⏭️ CAPTCHA unsolvable — marking for email outreach")
                result["attempts"].append(attempt_result)
                save_learned(learned)
                return result

            # PRE-SUBMIT: verify page is still active (Greenhouse can deactivate mid-session)
            if page.locator("text=/no longer active|deactivated|position.*filled|board.*not.*active/i").count() > 0:
                result["status"] = "job_closed"
                print(f"      ⏭️ Job board deactivated during session — skipping")
                result["attempts"].append(attempt_result)
                save_learned(learned)
                return result

            # SUBMIT
            submit_result = submit_and_verify(page, page_data, url)
            snap(page, f"submit_{attempt}")

            # EMAIL VERIFICATION: If submit returned email_verification_required,
            # the page has redirected to a security code prompt (Greenhouse pattern).
            # Wait for page to stabilize, then read code from Gmail and enter it.
            if not submit_result["submitted"] and submit_result.get("reason") == "email_verification_required":
                print("      📧 Security code page detected — attempting email verification...")
                try:
                    page.wait_for_timeout(2000)  # Let the security code page fully load
                    from src.email_code_reader import handle_email_verification
                    if handle_email_verification(page):
                        print("      ✅ Email verification completed — rechecking submit status")
                        snap(page, f"email_verified_{attempt}")
                        # Re-check for success signals after verification
                        try:
                            post_verify_text = page.locator("body").inner_text(timeout=5000).lower()
                        except Exception:
                            post_verify_text = ""
                        post_verify_url = page.url.lower()
                        success_signals_ev = ["thank", "success", "received", "submitted", "confirmation", "applied", "complete"]
                        if any(s in post_verify_url for s in success_signals_ev) or any(s in post_verify_text for s in success_signals_ev):
                            submit_result = {"submitted": True, "method": "email_verification"}
                        elif post_verify_url != url.lower().rstrip("/"):
                            submit_result = {"submitted": True, "method": "email_verification_redirect"}
                    else:
                        print("      ❌ handle_email_verification returned False — code not obtained or not entered")
                except Exception as ev_err:
                    print(f"      ⚠️ Email verification check failed: {str(ev_err)[:60]}")
            elif not submit_result["submitted"]:
                # Non-email-verification failures: try email verification as fallback
                # (page might show security code without submit_and_verify detecting it)
                try:
                    from src.email_code_reader import handle_email_verification
                    if handle_email_verification(page):
                        print("      ✅ Email verification completed (fallback) — rechecking submit status")
                        snap(page, f"email_verified_{attempt}")
                        try:
                            post_verify_text = page.locator("body").inner_text(timeout=5000).lower()
                        except Exception:
                            post_verify_text = ""
                        post_verify_url = page.url.lower()
                        success_signals_ev = ["thank", "success", "received", "submitted", "confirmation", "applied", "complete"]
                        if any(s in post_verify_url for s in success_signals_ev) or any(s in post_verify_text for s in success_signals_ev):
                            submit_result = {"submitted": True, "method": "email_verification"}
                        elif post_verify_url != url.lower().rstrip("/"):
                            submit_result = {"submitted": True, "method": "email_verification_redirect"}
                except Exception as ev_err:
                    print(f"      ⚠️ Email verification fallback check failed: {str(ev_err)[:60]}")

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

                # EMAIL VERIFICATION REQUIRED: don't retry submit — the page is waiting for a code.
                # handle_email_verification was already attempted above. If it failed, retrying
                # the form won't help — break out and mark as needing manual email verification.
                if submit_result.get("reason") == "email_verification_required":
                    result["status"] = "email_verification_failed"
                    result["fields_filled"] = attempt_result.get("filled", 0)
                    print(f"      📧 Email verification required but code not obtained — stopping retries")
                    result["attempts"].append(attempt_result)
                    save_learned(learned)
                    return result

                # DOCTOR: read error messages and try to fix
                errors = read_errors(page)
                if db:
                    from src.learning_engine import learn_from_failure
                    learn_from_failure(db, domain, url, [submit_result["reason"]] + errors, attempt)
                
                # DYNAMIC FIX: read errors, fix fields, fill remaining, retry submit
                total_fixed = 0
                if errors:
                    print(f"      🔧 Found {len(errors)} errors: {errors[:3]}")
                    fixed = fix_errors_and_retry(page, profile, errors)
                    total_fixed += fixed
                
                # Also run dynamic fill again (page may have revealed new required fields after submit attempt)
                dynamic_fixed = _fill_remaining_required(page, profile)
                total_fixed += dynamic_fixed
                
                if total_fixed > 0:
                    print(f"      🔄 Fixed {total_fixed} fields — retrying submit...")
                    snap(page, f"retry_submit_{attempt}")
                    # RETRY SUBMIT
                    page_data = read_page(page)
                    retry_result = submit_and_verify(page, page_data, url)
                    if retry_result["submitted"]:
                        result["status"] = "submitted"
                        result["fields_filled"] = attempt_result["filled"] + total_fixed
                        print(f"      ✅ SUBMITTED on retry via '{retry_result.get('method', '?')}'")
                        if db:
                            from src.learning_engine import learn_from_success, learn_selector
                            learn_from_success(db, domain, url, [f[1] for f in fill_result["filled"]], attempt_result["filled"] + total_fixed)
                        result["attempts"].append(attempt_result)
                        save_learned(learned)
                        return result
                    else:
                        print(f"      ❌ Retry also failed: {retry_result.get('reason', '?')}")

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
    run_applications._start_time = time.monotonic()
    profile = load_profile()
    learned = load_learned()
    results = []

    # Track same-session failures — key is "domain|company" for multi-tenant ATS,
    # plain domain for single-company sites.
    # Multi-tenant domains (greenhouse, lever, ashby) host 100s of companies —
    # one bad company must NOT block all others on that domain.
    MULTI_TENANT_DOMAINS = {"job-boards.greenhouse.io", "boards.greenhouse.io",
                            "jobs.lever.co", "jobs.ashbyhq.com"}
    session_failures = {}  # "domain|company" or "domain" -> failure count

    # Known CAPTCHA-free ATS domains — skip all stealth probing
    CAPTCHA_FREE_DOMAINS = {"jobs.lever.co", "lever.co", "boards.greenhouse.io",
                            "job-boards.greenhouse.io", "jobs.ashbyhq.com", "apply.workable.com"}

    # Log available stealth tools
    tools = list_available_tools()
    available = [t["name"] for t in tools if t["available"]]
    print(f"  🛡️ Stealth tools available: {', '.join(available)}")

    context = None
    # Try CloakBrowser first (stealth), fall back to regular Playwright
    try:
        if cloakbrowser:
            context = cloakbrowser.launch_context(headless=True)
            print(f"  CloakBrowser — stealth Chromium for automation")
        else:
            raise ImportError("cloakbrowser not installed")
    except Exception as cloak_err:
        print(f"  Using Playwright (cloakbrowser not available)")
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )

    # Inject Indeed cookies for authenticated apply
    indeed_cookies = load_indeed_cookies()
    if indeed_cookies:
        # Fix: convert int to bool for Playwright
        for c in indeed_cookies:
            if "secure" in c: c["secure"] = bool(c["secure"])
            if "httpOnly" in c: c["httpOnly"] = bool(c["httpOnly"])
        context.add_cookies(indeed_cookies)
        print(f"  🍪 Loaded {len(indeed_cookies)} Indeed cookies")

    # Rate limiting
    from cookie_agent import can_apply, record_apply, human_delay
    page = context.new_page()
    applied = 0

    for job in jobs:
        if applied >= max_apps:
            break
        # Wall-clock safety: stop if agent has been running too long
        _max_s = int(os.environ.get("AGENT_MAX_SECONDS", 35 * 60))
        if hasattr(run_applications, '_start_time') and (time.monotonic() - run_applications._start_time) > _max_s:
            print(f"\n  ⏰ Wall-clock limit reached — stopping applications gracefully")
            break
        url = job.get("url", "")
        domain = re.sub(r'https?://(www\.)?', '', url).split('/')[0]

        # Build failure-tracking key — multi-tenant ATS: per company, not per domain
        company_slug = re.sub(r'[^a-z0-9]', '', job.get("company", "unknown").lower())
        fail_key = f"{domain}|{company_slug}" if domain in MULTI_TENANT_DOMAINS else domain

        # Skip if this specific company/domain failed 2+ times this session
        if session_failures.get(fail_key, 0) >= 2:
            print(f"\n  ⏭️ Skipping {fail_key} — failed {session_failures[fail_key]}x this session")
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

        # Resolve company-hosted Greenhouse URLs (e.g., thoughtworks.com?gh_jid=123)
        # BEFORE the stealth precheck so CAPTCHA_FREE_DOMAINS check uses the real target URL.
        if "gh_jid=" in url and "greenhouse.io" not in url:
            _m = re.search(r'gh_jid=(\d+)', url)
            if _m:
                _co = job.get("company", "").lower().replace(" ", "")
                url = f"https://job-boards.greenhouse.io/{_co}/jobs/{_m.group(1)}"
                job["url"] = url
                domain = re.sub(r'https?://(www\.)?', '', url).split('/')[0]
                fail_key = f"{domain}|{company_slug}" if domain in MULTI_TENANT_DOMAINS else domain

        # SKIP STEALTH for known CAPTCHA-free ATS platforms
        is_captcha_free = any(d in url for d in CAPTCHA_FREE_DOMAINS)
        site_needs_cf_solve = False

        if is_captcha_free:
            print(f"    🟢 CAPTCHA-free ATS — direct access (no stealth needed)")
        else:
            # STEALTH PRE-CHECK: quick probe with curl_cffi to see if site is accessible
            # If it fails, DON'T skip — try Playwright + solve_cf_checkbox instead
            try:
                probe = fetch_curl_cffi(url)
                if probe and probe.success and "captcha" not in probe.html.lower() and "just a moment" not in probe.html.lower():
                    print(f"    🟢 Direct access OK ({probe.elapsed:.1f}s)")
                else:
                    # Try cloudscraper for cookies
                    cf_cookies = _try_cloudscraper(url)
                    if cf_cookies:
                        # Fix: convert int to bool for Playwright
                        for c in cf_cookies:
                            if "secure" in c: c["secure"] = bool(c["secure"])
                            if "httpOnly" in c: c["httpOnly"] = bool(c["httpOnly"])
                        context.add_cookies(cf_cookies)
                        print(f"    🟢 cloudscraper bypassed CF — injected {len(cf_cookies)} cookies")
                    else:
                        # Mark for CF solve AFTER page.goto — don't skip!
                        site_needs_cf_solve = True
                        print(f"    🟡 Site protected — will try Playwright + CF checkbox solve")
            except Exception as e:
                # Don't skip — try Playwright anyway
                site_needs_cf_solve = True
                print(f"    🟡 Stealth probe failed ({str(e)[:60]}) — will try Playwright directly")

        # For Lever jobs: try direct API POST first (no browser / no CAPTCHA)
        if "lever.co/" in url:
            from src.lever_api import submit_lever_api
            _resume = profile.get("resume_path",
                                  "~/Downloads/CV/Bob_Rikh_Java_Backend_Developer_C2C.pdf")
            _api = submit_lever_api(url, profile, _resume, dry_run=dry_run)
            if _api.get("submitted"):
                print(f"    ✅ Lever direct API: {_api.get('method', 'ok')}")
                r = {
                    "url": url, "title": job.get("title", ""),
                    "company": job.get("company", ""),
                    "status": "dry_run" if dry_run else "submitted",
                    "method": "lever_api", "fields_filled": 5,
                }
                results.append(r)
                applied += 1
                record_apply(site_key)
                human_delay(site_key)
                continue
            print(f"    ⚠️ Lever API failed ({_api.get('error','?')[:80]}) — browser fallback")

        # For Greenhouse jobs: try direct multipart POST first (no browser / no CAPTCHA risk)
        if "greenhouse.io" in url:
            from src.greenhouse_api import submit_greenhouse_api
            _resume = profile.get("resume_path",
                                  "~/Downloads/CV/Bob_Rikh_Java_Backend_Developer_C2C.pdf")
            _api = submit_greenhouse_api(url, profile, _resume, dry_run=dry_run)
            if _api.get("submitted"):
                print(f"    ✅ Greenhouse direct API: {_api.get('method', 'ok')}")
                r = {
                    "url": url, "title": job.get("title", ""),
                    "company": job.get("company", ""),
                    "status": "dry_run" if dry_run else "submitted",
                    "method": "direct_api", "fields_filled": 5,
                }
                results.append(r)
                applied += 1
                record_apply(site_key)
                human_delay(site_key)
                continue
            print(f"    ⚠️ GH API failed ({_api.get('error','?')[:80]}) — browser fallback")

        # Per-job timeout: max 3 minutes per application attempt
        PER_JOB_TIMEOUT = 180  # seconds
        _job_start = time.monotonic()
        try:
            r = apply_to_job(page, profile, job, learned, dry_run, db=db, site_needs_cf_solve=site_needs_cf_solve)
        except PwTimeout:
            elapsed = int(time.monotonic() - _job_start)
            print(f"    ⏰ Job timed out after {elapsed}s — skipping")
            r = {"url": url, "title": job.get("title", ""), "company": job.get("company", ""),
                 "status": "timeout", "reason": f"Exceeded {PER_JOB_TIMEOUT}s"}
        except Exception as e:
            print(f"    💥 Unexpected error: {str(e)[:80]}")
            r = {"url": url, "title": job.get("title", ""), "company": job.get("company", ""),
                 "status": "error", "reason": str(e)[:200]}

        # If the job took too long (>3 min), note for next time
        _job_elapsed = time.monotonic() - _job_start
        if _job_elapsed > PER_JOB_TIMEOUT:
            print(f"    ⚠️ Job took {int(_job_elapsed)}s (limit {PER_JOB_TIMEOUT}s)")

        results.append(r)
        if r["status"] in ("submitted", "dry_run"):
            applied += 1
            record_apply(site_key)
            human_delay(site_key)  # Random wait to look human
        else:
            # Track per-company failures for multi-tenant ATS, per-domain for others
            if r["status"] in ("failed_all_retries", "captcha_blocked"):
                session_failures[fail_key] = session_failures.get(fail_key, 0) + 1
            wait(1, 2)

    context.close()

    save_learned(learned)
    ok = sum(1 for r in results if r["status"] in ("submitted", "dry_run"))
    print(f"\n  📊 {ok}/{len(results)} applied | Learned selectors for {len(learned.get('winning_selectors', {}))} domains")
    return results
