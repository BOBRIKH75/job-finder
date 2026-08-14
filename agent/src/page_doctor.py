"""Page doctor — diagnoses and fixes page issues that block form filling.

Handles:
- Cookie banners / consent popups blocking the form
- Error messages after filling (wrong format, required field)
- Custom dropdowns (React Select, Material UI, Ant Design)
- Date pickers (type date string instead of using picker)
- Phone format validation (strips/adds formatting)
- Modal dialogs that appear mid-form
- "Next" / "Continue" buttons for multi-step forms
- Captcha detection (flags for skip)
"""
import re, time, random
from pathlib import Path

LEARNED_ISSUES_FILE = Path(__file__).parent.parent / "data" / "learned_issues.json"


def dismiss_popups(page) -> int:
    """Close cookie banners, modals, overlays that block the form."""
    dismissed = 0
    # Cookie consent buttons
    for text in ["Accept", "Accept All", "Accept Cookies", "I Agree", "Got it", "OK", "Close", "Dismiss", "×", "✕"]:
        try:
            btn = page.locator(f'button:has-text("{text}"), a:has-text("{text}"), [aria-label="Close"]').first
            if btn.is_visible(timeout=1000):
                btn.click()
                dismissed += 1
                time.sleep(0.5)
        except Exception:
            continue
    # Close modals by clicking overlay/backdrop
    for sel in ['.modal-backdrop', '.overlay', '[class*="backdrop"]', '[class*="overlay"]']:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=500):
                page.keyboard.press("Escape")
                dismissed += 1
                time.sleep(0.5)
        except Exception:
            continue
    return dismissed


def read_errors(page) -> list[str]:
    """Read all visible error messages on the page."""
    errors = []
    for sel in ['.error', '.field-error', '.form-error', '[class*="error"]',
                '[class*="invalid"]', '[role="alert"]', '.validation-message',
                '.help-block.error', '[class*="ErrorMessage"]']:
        try:
            for el in page.locator(sel).all():
                text = el.inner_text(timeout=500).strip()
                if text and len(text) < 200:
                    errors.append(text)
        except Exception:
            continue
    return list(set(errors))


def fix_field_format(field_label: str, value: str) -> str:
    """Fix value format based on what the field expects."""
    label = field_label.lower()

    # Phone: try different formats
    if "phone" in label or "mobile" in label or "tel" in label:
        digits = re.sub(r'\D', '', value)
        if len(digits) == 10:
            return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"  # (347) 268-5917
        if len(digits) == 11 and digits[0] == '1':
            return f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        return value

    # Zip code: just digits
    if "zip" in label or "postal" in label:
        return re.sub(r'\D', '', value)[:5]

    # Salary: just number
    if "salary" in label or "compensation" in label or "pay" in label:
        if "$" in value:
            nums = re.findall(r'\d+', value.replace(",", ""))
            if nums:
                return nums[0]
        return value

    # URL fields: ensure https://
    if "linkedin" in label or "github" in label or "url" in label or "website" in label:
        if value and not value.startswith("http"):
            return "https://" + value
        return value

    return value


def handle_custom_dropdown(page, selector: str, target_value: str) -> bool:
    """Handle non-standard dropdowns (React Select, Material UI, etc.)."""
    # Strategy 1: Click to open, then type to filter, then select
    try:
        el = page.locator(selector).first
        el.click()
        time.sleep(0.5)

        # Look for opened dropdown options
        for opt_sel in ['[class*="option"]', '[class*="menu-item"]', '[role="option"]',
                        '[class*="listbox"] li', '.dropdown-item', '[class*="Option"]']:
            options = page.locator(opt_sel).all()
            for opt in options:
                try:
                    text = opt.inner_text(timeout=500)
                    if target_value.lower() in text.lower():
                        opt.click()
                        return True
                except Exception:
                    continue

        # Strategy 2: Type into the search input inside the dropdown
        for input_sel in ['[class*="input"] input', '[class*="search"] input', 'input[role="combobox"]']:
            try:
                inp = page.locator(input_sel).first
                if inp.is_visible(timeout=500):
                    inp.fill(target_value)
                    time.sleep(0.5)
                    # Click first visible option
                    page.locator('[class*="option"]:visible, [role="option"]:visible').first.click()
                    return True
            except Exception:
                continue

        # Strategy 3: Press Escape and try select_option
        page.keyboard.press("Escape")
        return False
    except Exception:
        return False


def handle_date_field(page, selector: str, value: str = "2026-05-01") -> bool:
    """Handle date picker fields."""
    try:
        el = page.locator(selector).first
        # Try direct fill first (works for input[type=date])
        el.fill(value)
        return True
    except Exception:
        pass
    try:
        # Try typing the date
        el = page.locator(selector).first
        el.click()
        page.keyboard.type(value.replace("-", "/"))
        return True
    except Exception:
        return False


def click_next_button(page) -> bool:
    """Find and click Next/Continue button for multi-step forms."""
    for text in ["Next", "Continue", "Next Step", "Proceed", "Next Page", "Save and Continue", "Save & Continue"]:
        try:
            btn = page.locator(f'button:has-text("{text}"), a:has-text("{text}"), input[value="{text}"]').first
            if btn.is_visible(timeout=1000):
                btn.click()
                time.sleep(1.5)
                page.wait_for_load_state("networkidle", timeout=10000)
                return True
        except Exception:
            continue
    return False


def detect_captcha(page) -> bool:
    """Check if page has a VISIBLE CAPTCHA that blocks form filling."""
    try:
        return page.evaluate("""() => {
            const sels = ['.g-recaptcha', '.h-captcha', '.cf-turnstile', '[data-captcha]', '#captcha', '.captcha'];
            for (const s of sels) {
                const el = document.querySelector(s);
                if (el && el.offsetHeight > 0 && el.offsetWidth > 0) return true;
            }
            // Check for challenge pages (full-page CAPTCHA)
            const body = document.body.innerText.toLowerCase();
            if (body.includes('verify you are human') || body.includes('one more step') || body.includes('checking your browser'))
                return true;
            return false;
        }""")
    except Exception:
        return False


def detect_turnstile(page) -> str | None:
    """Return the Turnstile sitekey if a cf-turnstile widget is on the page, else None."""
    try:
        return page.evaluate("""() => {
            const el = document.querySelector('.cf-turnstile, [data-sitekey]');
            return el ? el.getAttribute('data-sitekey') : null;
        }""")
    except Exception:
        return None


def solve_turnstile_via_docker(page, url: str) -> bool:
    """Try to solve a Turnstile CAPTCHA using the Theyka/Turnstile-Solver Docker service.

    The service runs at TURNSTILE_SOLVER_URL (default http://localhost:5000).
    It opens a real browser internally, solves the challenge, returns the token.
    We inject the token into the page's hidden input and the form can submit.

    Returns True if solved, False if not available or failed.
    """
    import os, time
    solver_url = os.environ.get("TURNSTILE_SOLVER_URL", "")
    if not solver_url:
        return False

    sitekey = detect_turnstile(page)
    if not sitekey:
        return False

    print(f"      🔓 Turnstile detected (sitekey={sitekey[:20]}...) — calling solver...")
    try:
        import requests as _req
        # Submit solve request
        resp = _req.get(f"{solver_url}/turnstile",
                        params={"url": url, "sitekey": sitekey}, timeout=10)
        task_id = resp.json().get("task_id")
        if not task_id:
            print(f"      ⚠️  Solver returned no task_id")
            return False

        # Poll for token (typically 4-8 seconds)
        for _ in range(20):
            time.sleep(2)
            r = _req.get(f"{solver_url}/result",
                         params={"id": task_id}, timeout=10).json()
            if "value" in r:
                token = r["value"]
                # Inject token into the page
                page.evaluate(f"""(token) => {{
                    // Set the hidden input that Turnstile populates
                    const inp = document.querySelector('[name="cf-turnstile-response"]');
                    if (inp) inp.value = token;
                    // Also try the callback approach
                    const cb = document.querySelector('.cf-turnstile');
                    if (cb && cb.getAttribute('data-callback')) {{
                        const fn = window[cb.getAttribute('data-callback')];
                        if (fn) fn(token);
                    }}
                }}""", token)
                print(f"      ✅ Turnstile solved in {r.get('elapsed_time', '?')}s — token injected")
                return True

        print(f"      ⚠️  Turnstile solver timed out")
        return False
    except Exception as e:
        print(f"      ⚠️  Turnstile solver error: {e}")
        return False


def detect_captcha_type(page) -> dict | None:
    """Detect CAPTCHA type and sitekey. Returns {type, sitekey, url} or None."""
    try:
        return page.evaluate("""() => {
            const r = {};
            const url = window.location.href;
            const hc = document.querySelector('.h-captcha, [data-hcaptcha-sitekey]');
            if (hc) { r.type = 'hcaptcha'; r.sitekey = hc.dataset.sitekey || hc.dataset.hcaptchaSitekey; }
            if (!r.type && document.querySelector('script[src*="hcaptcha.com"], iframe[src*="hcaptcha.com"]')) {
                const el = document.querySelector('[data-sitekey]');
                if (el) { r.type = 'hcaptcha'; r.sitekey = el.dataset.sitekey; }
            }
            if (!r.type) {
                const cf = document.querySelector('.cf-turnstile, [data-turnstile-sitekey]');
                if (cf) { r.type = 'turnstile'; r.sitekey = cf.dataset.sitekey || cf.dataset.turnstileSitekey; }
            }
            if (!r.type) {
                const s = document.querySelector('script[src*="recaptcha"][src*="render="]');
                if (s) { const m = s.src.match(/render=([^&]+)/); if (m && m[1] !== 'explicit') { r.type = 'recaptchav3'; r.sitekey = m[1]; } }
            }
            if (!r.type) {
                const rc = document.querySelector('.g-recaptcha');
                if (rc) { r.type = 'recaptchav2'; r.sitekey = rc.dataset.sitekey; }
            }
            if (!r.type && document.querySelector('script[src*="recaptcha"]')) {
                const el = document.querySelector('[data-sitekey]');
                if (el) { r.type = 'recaptchav2'; r.sitekey = el.dataset.sitekey; }
            }
            if (r.type) { r.url = url; return r; }
            return null;
        }""")
    except Exception:
        return None


def solve_recaptcha_v2_docker(page, url: str) -> bool:
    """Solve reCAPTCHA v2 via playwright-recaptcha library (audio + speech recognition). FREE, no Docker."""
    print(f"      🔓 reCAPTCHA v2 — solving via audio challenge...")
    try:
        from playwright_recaptcha import recaptchav2
        with recaptchav2.SyncSolver(page) as solver:
            token = solver.solve_recaptcha(wait=True)
            if token and len(token) > 20:
                print(f"      ✅ reCAPTCHA v2 solved via audio!")
                return True
    except Exception as e:
        err = str(e)
        if "rate limit" in err.lower():
            print(f"      ⚠️  reCAPTCHA rate limited (too many attempts from this IP)")
        else:
            print(f"      ⚠️  reCAPTCHA v2 audio solve failed: {err[:80]}")
    return False


def solve_recaptcha_v3_http(page, captcha_info: dict) -> bool:
    """Solve reCAPTCHA v3 via PyPasser HTTP bypass. FREE, no browser needed."""
    sitekey = captcha_info.get("sitekey", "")
    if not sitekey:
        return False
    anchor_url = f"https://www.google.com/recaptcha/api2/anchor?ar=1&k={sitekey}&co=aHR0cHM6Ly93d3cuZ29vZ2xlLmNvbQ..&v=jF0Oy4JxFv0&size=invisible"
    print(f"      🔓 reCAPTCHA v3 — trying PyPasser HTTP bypass...")
    try:
        from pypasser import reCaptchaV3
        token = reCaptchaV3(anchor_url, timeout=15)
        if token and len(token) > 20:
            page.evaluate("""(token) => {
                document.querySelectorAll('[name="g-recaptcha-response"]').forEach(el => { el.value = token; });
            }""", token)
            print(f"      ✅ reCAPTCHA v3 solved via HTTP")
            return True
    except Exception:
        pass
    print(f"      ⚠️  reCAPTCHA v3 HTTP bypass failed")
    return False


def solve_via_ohmycaptcha(page, captcha_info: dict) -> bool:
    """Solve ANY CAPTCHA via OhMyCaptcha self-hosted service (createTask/getTaskResult API).

    Supports: reCAPTCHA v2/v3, hCaptcha, Turnstile, FunCaptcha — all free, self-hosted.
    Runs as Docker sidecar at OHMYCAPTCHA_URL (default http://localhost:8002).
    """
    import os, time
    base = os.environ.get("OHMYCAPTCHA_URL", "")
    if not base:
        return False

    ctype = captcha_info.get("type", "")
    sitekey = captcha_info.get("sitekey", "")
    url = captcha_info.get("url", "")
    if not ctype or not sitekey:
        return False

    # Map our type names to OhMyCaptcha task types
    task_type_map = {
        "turnstile": "TurnstileTaskProxyless",
        "recaptchav2": "NoCaptchaTaskProxyless",
        "recaptchav3": "RecaptchaV3TaskProxyless",
        "hcaptcha": "HCaptchaTaskProxyless",
    }
    task_type = task_type_map.get(ctype)
    if not task_type:
        return False

    client_key = os.environ.get("OHMYCAPTCHA_KEY", "default")
    print(f"      🧩 OhMyCaptcha: solving {ctype} via {task_type}...")

    try:
        import requests as _req
        # Step 1: createTask
        task = {"type": task_type, "websiteURL": url, "websiteKey": sitekey}
        if ctype == "recaptchav3":
            task["pageAction"] = "submit"
        resp = _req.post(f"{base}/createTask", json={"clientKey": client_key, "task": task}, timeout=15)
        data = resp.json()
        if data.get("errorId", 1) != 0:
            print(f"      ⚠️  OhMyCaptcha createTask error: {data.get('errorDescription', 'unknown')}")
            return False
        task_id = data.get("taskId", "")
        if not task_id:
            return False

        # Step 2: poll getTaskResult
        for _ in range(20):
            time.sleep(3)
            r = _req.post(f"{base}/getTaskResult", json={"clientKey": client_key, "taskId": task_id}, timeout=10).json()
            status = r.get("status", "")
            if status == "ready":
                sol = r.get("solution", {})
                token = sol.get("gRecaptchaResponse") or sol.get("token") or ""
                if token and len(token) > 20:
                    # Step 3: inject token
                    _inject_captcha_token(page, ctype, token)
                    print(f"      ✅ OhMyCaptcha solved {ctype}")
                    return True
            elif status != "processing":
                print(f"      ⚠️  OhMyCaptcha status: {status}")
                return False

        print(f"      ⚠️  OhMyCaptcha timed out")
        return False
    except Exception as e:
        print(f"      ⚠️  OhMyCaptcha error: {e}")
        return False


def _inject_captcha_token(page, ctype: str, token: str):
    """Inject a solved CAPTCHA token into the page."""
    if ctype in ("recaptchav2", "recaptchav3"):
        page.evaluate("""(token) => {
            document.querySelectorAll('[name="g-recaptcha-response"]').forEach(el => { el.value = token; });
            if (window.___grecaptcha_cfg) {
                const clients = window.___grecaptcha_cfg.clients;
                for (const key in clients) {
                    const walk = (obj, d) => {
                        if (d > 4 || !obj) return;
                        for (const k in obj) {
                            if (typeof obj[k] === 'function' && k.length < 3) try { obj[k](token); } catch(e) {}
                            else if (typeof obj[k] === 'object') walk(obj[k], d+1);
                        }
                    };
                    walk(clients[key], 0);
                }
            }
        }""", token)
    elif ctype == "hcaptcha":
        page.evaluate("""(token) => {
            const ta = document.querySelector('[name="h-captcha-response"], textarea[name*="hcaptcha"]');
            if (ta) ta.value = token;
            document.querySelectorAll('iframe[data-hcaptcha-response]').forEach(f => f.setAttribute('data-hcaptcha-response', token));
        }""", token)
    elif ctype == "turnstile":
        page.evaluate("""(token) => {
            const inp = document.querySelector('[name="cf-turnstile-response"], input[name*="turnstile"]');
            if (inp) inp.value = token;
        }""", token)


def solve_captcha(page, url: str) -> bool:
    """Full CAPTCHA solve chain — tries all free solvers by type.

    Priority order:
    1. OhMyCaptcha (universal — solves ALL types via self-hosted Docker)
    2. Type-specific fallbacks:
       Turnstile  → Theyka Docker sidecar
       reCAPTCHA v2 → sarperavci audio Docker sidecar
       reCAPTCHA v3 → PyPasser HTTP bypass
       hCaptcha   → OhMyCaptcha only (no other free solver)
    """
    captcha_info = detect_captcha_type(page)
    if not captcha_info:
        if not detect_captcha(page):
            return True  # No CAPTCHA
        # Can't identify type — try Turnstile as default
        return solve_turnstile_via_docker(page, url)

    ctype = captcha_info["type"]
    print(f"      🔍 CAPTCHA: {ctype} (sitekey={captcha_info.get('sitekey', '?')[:20]}...)")

    # Try OhMyCaptcha first — handles ALL types
    if solve_via_ohmycaptcha(page, captcha_info):
        return True

    # Fallback to type-specific solvers
    if ctype == "turnstile":
        return solve_turnstile_via_docker(page, url)
    if ctype == "recaptchav2":
        return solve_recaptcha_v2_docker(page, url)
    if ctype == "recaptchav3":
        return solve_recaptcha_v3_http(page, captcha_info)
    if ctype == "hcaptcha":
        print(f"      ⚠️  hCaptcha — OhMyCaptcha failed, no other free solver")
        return False
    return False


def fill_greenhouse_custom_fields(page, profile: dict) -> int:
    """Handle Greenhouse's React Select combobox dropdowns.
    
    Greenhouse renders dropdowns as:
      <input role="combobox" aria-haspopup="true" aria-required="true" id="question_XXX">
    With label at: <label id="question_XXX-label">Question text</label>
    
    To fill: click the input → type answer text → wait for options → click matching option.
    """
    filled = 0
    
    # Answers keyed by substring match in the label text
    GH_ANSWERS = {
        "require immigration sponsorship": "No",
        "require sponsorship": "No",
        "immigration sponsorship": "No",
        "visa sponsor": "No",
        "authorized to work": "Yes",
        "which u.s. state": "Colorado",
        "state or canadian province": "Colorado",
        "reside in": "Colorado",
        "how did you first learn": "Indeed",
        "how did you hear": "Indeed",
        "previously been employed": "not previously",
        "previously employed": "No",
        "pronoun": "He/him",
        "gender": "prefer not to say",
        "race": "prefer not to say",
        "ethnicity": "prefer not to say",
    }
    
    try:
        # Find all required React Select comboboxes
        comboboxes = page.locator('input[role="combobox"][aria-required="true"]').all()
        
        for combo in comboboxes:
            try:
                combo_id = combo.get_attribute("id") or ""
                # Skip the "country" select (already handled by standard fill)
                if combo_id == "country":
                    continue
                    
                # Check if already has a value selected
                value_container = combo.locator("xpath=ancestor::div[contains(@class,'select__control')]//div[contains(@class,'single-value')]")
                try:
                    if value_container.count() > 0 and value_container.first.inner_text(timeout=300).strip():
                        continue  # Already filled
                except Exception:
                    pass
                
                # Get label text
                label_text = ""
                label_id = combo.get_attribute("aria-labelledby") or ""
                if label_id:
                    try:
                        label_text = page.locator(f"#{label_id}").first.inner_text(timeout=500)
                    except Exception:
                        pass
                if not label_text:
                    try:
                        label_text = combo.get_attribute("aria-label") or ""
                    except Exception:
                        pass
                
                if not label_text:
                    continue
                
                # Find matching answer
                answer = None
                label_lower = label_text.lower()
                for key, val in GH_ANSWERS.items():
                    if key in label_lower:
                        answer = val
                        break
                
                if not answer:
                    continue
                
                # Fill the combobox: click → type → select option
                combo.click()
                time.sleep(0.3)
                combo.fill(answer)
                time.sleep(0.5)
                
                # Click the first visible option
                option_clicked = False
                for opt_sel in ['[role="option"]', '.select__option', '[class*="option"]']:
                    options = page.locator(opt_sel).all()
                    for opt in options:
                        try:
                            if opt.is_visible(timeout=300):
                                opt_text = opt.inner_text(timeout=300)
                                if answer.lower() in opt_text.lower():
                                    opt.click()
                                    option_clicked = True
                                    filled += 1
                                    time.sleep(0.3)
                                    break
                        except Exception:
                            continue
                    if option_clicked:
                        break
                
                # If no exact match, click first visible option
                if not option_clicked:
                    try:
                        first_opt = page.locator('[role="option"]').first
                        if first_opt.is_visible(timeout=500):
                            first_opt.click()
                            option_clicked = True
                            filled += 1
                            time.sleep(0.3)
                    except Exception:
                        pass
                
                if not option_clicked:
                    page.keyboard.press("Escape")
                    
            except Exception:
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                continue
        
        # Also fill "Preferred Name" if empty (common Greenhouse required field)
        try:
            for sel in ['input[aria-label="Preferred Name"]', 'input[aria-label*="Preferred"]']:
                pref = page.locator(sel).first
                if pref.is_visible(timeout=500):
                    val = pref.input_value(timeout=300)
                    if not val:
                        first_name = profile.get("first_name", "")
                        if not first_name and profile.get("name"):
                            first_name = profile["name"].split()[0]
                        if first_name:
                            pref.fill(first_name)
                            filled += 1
                    break
        except Exception:
            pass
        
        # Fill Country combobox (United States)
        try:
            country_combo = page.locator('#country').first
            if country_combo.is_visible(timeout=500):
                val = country_combo.input_value(timeout=300)
                if not val:
                    country_combo.click()
                    time.sleep(0.3)
                    country_combo.fill("United States")
                    time.sleep(0.5)
                    us_option = page.locator('[role="option"]:has-text("United States")').first
                    if us_option.is_visible(timeout=500):
                        us_option.click()
                        filled += 1
                        time.sleep(0.3)
        except Exception:
            pass
            
    except Exception:
        pass
    
    if filled:
        print(f"      🔽 Filled {filled} Greenhouse custom dropdowns")
    
    return filled


def detect_multi_step(page) -> bool:
    """Check if this is a multi-step form (has progress indicator or Next button)."""
    signals = ['step', 'progress', 'wizard', 'stage', 'page 1', 'step 1']
    try:
        text = page.locator("body").inner_text(timeout=3000).lower()
        return any(s in text for s in signals)
    except Exception:
        return False


def fix_errors_and_retry(page, profile: dict, errors: list[str]) -> int:
    """Analyze error messages and try to fix the fields that caused them."""
    fixed = 0
    for error in errors:
        lower = error.lower()

        # "Email is required" / "Please enter email"
        if "email" in lower and ("required" in lower or "enter" in lower or "valid" in lower):
            try:
                for sel in ['input[type="email"]', 'input[name*="email"]', '#email']:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=500):
                        el.fill(profile.get("email", ""))
                        fixed += 1
                        break
            except Exception:
                pass

        # "Phone number is invalid"
        if "phone" in lower and ("invalid" in lower or "format" in lower or "required" in lower):
            phone = profile.get("phone", "")
            digits = re.sub(r'\D', '', phone)
            formatted = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}" if len(digits) == 10 else phone
            try:
                for sel in ['input[type="tel"]', 'input[name*="phone"]', '#phone']:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=500):
                        el.fill("")
                        el.fill(formatted)
                        fixed += 1
                        break
            except Exception:
                pass

        # "Name is required"
        if "name" in lower and "required" in lower:
            try:
                for sel in ['input[name="name"]', '#name', 'input[name*="name"]']:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=500):
                        el.fill(profile.get("name", ""))
                        fixed += 1
                        break
            except Exception:
                pass

        # "Resume is required" / "Please upload"
        if ("resume" in lower or "cv" in lower) and ("required" in lower or "upload" in lower):
            resume = Path(__file__).parent.parent / "resume.pdf"
            if resume.exists():
                try:
                    page.locator('input[type="file"]').first.set_input_files(str(resume))
                    fixed += 1
                except Exception:
                    pass

        # "Location is required" / "City is required"
        if ("location" in lower or "city" in lower) and "required" in lower:
            try:
                for sel in ['input[name*="location"]', 'input[name*="city"]', '#location', '#city',
                            'input[placeholder*="city"]', 'input[placeholder*="location"]']:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=500):
                        el.fill(profile.get("location", profile.get("city", "Parker, CO")))
                        fixed += 1
                        break
            except Exception:
                pass

        # "This field is required" / generic required — try filling all empty visible required inputs
        if "required" in lower and not any(k in lower for k in ["email", "phone", "name", "resume", "location", "city"]):
            try:
                # Find all required inputs that are still empty
                empty_required = page.locator('input[required]:not([type="hidden"]):not([type="file"])').all()
                for inp in empty_required:
                    try:
                        val = inp.input_value(timeout=500)
                        if not val or val.strip() == "":
                            # Try to figure out what this field is
                            name = inp.get_attribute("name") or ""
                            placeholder = inp.get_attribute("placeholder") or ""
                            label_text = name + " " + placeholder
                            
                            # Map common field names to profile values
                            field_mapping = {
                                "linkedin": profile.get("linkedin", ""),
                                "github": profile.get("github", ""),
                                "website": profile.get("linkedin", ""),
                                "company": profile.get("company", ""),
                                "address": profile.get("location", ""),
                                "street": profile.get("location", ""),
                                "country": "United States",
                                "state": profile.get("state", "CO"),
                                "zip": profile.get("zip", "80134"),
                            }
                            
                            for key, value in field_mapping.items():
                                if key in label_text.lower() and value:
                                    inp.fill(value)
                                    fixed += 1
                                    break
                    except Exception:
                        continue
            except Exception:
                pass

    # Also try filling empty required select dropdowns
    try:
        empty_selects = page.locator('select[required]').all()
        for sel in empty_selects:
            try:
                current = sel.input_value(timeout=500)
                if not current:
                    # Select first non-empty option
                    options = sel.locator('option').all()
                    for opt in options[1:]:  # skip first (usually "Select...")
                        val = opt.get_attribute("value")
                        if val:
                            sel.select_option(value=val)
                            fixed += 1
                            break
            except Exception:
                continue
    except Exception:
        pass

    return fixed
