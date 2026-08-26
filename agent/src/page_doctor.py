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

# Gemini Flash free CAPTCHA solver (fallback when CapSolver has no balance)
try:
    from src.gemini_captcha_solver import solve_captcha_with_gemini
except ImportError:
    try:
        from gemini_captcha_solver import solve_captcha_with_gemini
    except ImportError:
        solve_captcha_with_gemini = None

LEARNED_ISSUES_FILE = Path(__file__).parent.parent / "data" / "learned_issues.json"


def dismiss_popups(page) -> int:
    """Close cookie banners, modals, overlays that block the form."""
    dismissed = 0
    # Cookie consent buttons
    for text in ["Accept", "Accept All", "Allow All", "ALLOW ALL", "Allow Selection", "Accept Cookies", "I Agree", "Agree", "Got it", "OK", "Close", "Dismiss", "Deny", "Reject", "×", "✕", "Continue"]:
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


def solve_cf_checkbox(page, max_attempts: int = 2) -> bool:
    """Try to solve Cloudflare 'Verify you are human' by clicking the challenges iframe.
    
    Tested manually 2026-08-17: works on Indeed.com.
    Flow: find challenges.cloudflare.com iframe → click inside → wait 5s → check if passed.
    """
    import time
    for attempt in range(max_attempts):
        try:
            title = page.title().lower()
            body_text = page.evaluate("() => document.body.innerText.substring(0, 300)").lower()
            if "just a moment" not in title and "verify you are human" not in body_text and "additional verification" not in body_text:
                return True  # Already passed
            
            # Find the Cloudflare challenges iframe
            for frame in page.frames:
                if "challenges" in frame.url or "turnstile" in frame.url:
                    time.sleep(2)  # Wait before clicking (like a human)
                    frame.click("body", timeout=5000)
                    print(f"      ✅ Clicked CF checkbox (attempt {attempt + 1})")
                    time.sleep(5)  # Wait for verification
                    break
            else:
                # No iframe found, try clicking any checkbox on page
                try:
                    page.click("input[type=checkbox]", timeout=3000)
                    time.sleep(5)
                except Exception:
                    pass
            
            # Check if passed
            title = page.title().lower()
            if "just a moment" not in title and "additional verification" not in title:
                print("      ✅ CF bypass successful!")
                return True
        except Exception:
            pass
    
    return False


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
        # Try Gemini visual solver as free fallback
        if solve_captcha_with_gemini:
            print(f"      🤖 hCaptcha: trying Gemini Flash visual solver (free fallback)...")
            if solve_captcha_with_gemini(page, "hcaptcha"):
                return True
        print(f"      ⚠️  hCaptcha — OhMyCaptcha + Gemini failed, no other free solver")
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
        "country": "United States",
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
        "gender": "Decline To Self Identify",
        "race": "Decline To Self Identify",
        "ethnicity": "Decline To Self Identify",
        "race/ethnicity": "Decline To Self Identify",
        "how do you identify": "Decline To Self Identify",
        "gender identity": "Decline To Self Identify",
        "hispanic/latino": "No",
        "hispanic": "No",
        "latino": "No",


        "disability status": "I do not want to answer",
        "disability": "I do not want to answer",
        "do you have a disability": "I do not want to answer",
        "language": "English",
        "languages you speak": "English",
        "fluent": "English",
        "willing to travel": "No",
        "travel": "No",
        "work arrangement": "Remote",
        "work model": "Remote",
        "employment type": "Contract",
        "relocate": "No",
        "years of experience": "10",
        # AI consent (Greenhouse 2025+ pattern)
        "consenting to the use of ai": "Yes",
        "consent to the use of ai": "Yes",
        "use of ai for evaluating": "Yes",
        "ai for evaluating my candidacy": "Yes",
        "ai to evaluate": "Yes",
        "use of artificial intelligence": "Yes",
        # Other consent/acknowledge patterns
        "acknowledge": "Yes",
        "agree to": "Yes",
        "consent": "Yes",
        # Canonical-specific questions
        "how many companies": "4",
        "past ten years": "4",
        "privacy notice": "Yes",
        "privacy policy": "Yes",
        "confirm that you have read": "Yes",
        "read and agree": "Yes",
        # Immigration / work auth
        "alien illegally": "No",
        "unlawfully in the united states": "No",
        "legally authorized to work": "Yes",
        "now or in the future require sponsorship": "No",
        "eligible to work": "Yes",
        "work permit": "Yes",
        # Location
        "location (city)": "Parker, CO",
        "city": "Parker",
        "where are you located": "Parker, CO",
        "current location": "Parker, CO",
        # Interest / motivation (short answer for textareas)
        "why are you interested": "I'm passionate about the company's mission and believe my 10+ years of Java/Spring Boot experience with distributed systems, Kafka, and cloud-native architectures align well with this role. I'm excited to contribute to impactful engineering challenges.",
        "what interests you": "I'm passionate about the company's mission and believe my 10+ years of Java/Spring Boot experience with distributed systems, Kafka, and cloud-native architectures align well with this role.",
        "why do you want to work": "I'm drawn to the technical challenges and the opportunity to apply my expertise in microservices, event-driven architecture, and cloud platforms at scale.",
        "tell us about yourself": "Senior Java Backend Developer with 10+ years of experience building microservices with Spring Boot, Kafka, Kubernetes, and AWS. Passionate about clean architecture, system reliability, and mentoring teams.",
        # Technology experience
        "describe your experience": "10+ years building distributed systems with Java/Spring Boot, Apache Kafka, Kubernetes, AWS (EKS, S3, DocumentDB), MongoDB, Cassandra, PostgreSQL, Redis, Docker, and Terraform. Experienced with event-driven architectures, CI/CD pipelines (GitLab/Jenkins), and observability (DataDog, Splunk).",
        "technologies": "Java, Spring Boot, Kafka, Kubernetes, Docker, AWS, MongoDB, Cassandra, PostgreSQL, Redis, GraphQL, REST APIs",
    }
    
    try:
        # Find all required React Select comboboxes
        comboboxes = page.locator('input[role="combobox"]').all()
        
        for combo in comboboxes:
            try:
                combo_id = combo.get_attribute("id") or ""
                
                # Skip phone country code dropdown (not a question)
                if "iti-" in combo_id or "search-input" in combo_id:
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
                    # Fallback: use element ID as label hint
                    label_text = combo_id
                
                if not label_text:
                    continue
                
                # Find matching answer
                answer = None
                label_lower = label_text.lower()
                
                # ID-based matching for known EEO fields (Greenhouse IDs)
                ID_ANSWERS = {
                    "gender": "Decline To Self Identify",
                    "hispanic_ethnicity": "No",
                    "veteran_status": "I am not a protected",
                    "disability_status": "I do not want to answer",
                }
                if combo_id in ID_ANSWERS:
                    answer = ID_ANSWERS[combo_id]
                
                if not answer:
                    for key, val in GH_ANSWERS.items():
                        if key in label_lower:
                            answer = val
                            break
                
                if not answer:
                    # No known answer — for ANY unfilled combobox, try selecting first option
                    # This handles EEO fields with no label (id like 4028768003)
                    try:
                        combo.click()
                        time.sleep(0.5)
                        # Look for "Decline" or "prefer not" option first
                        options = page.locator('[role="option"]').all()
                        decline_clicked = False
                        for opt in options:
                            opt_text = opt.inner_text(timeout=300).lower()
                            if any(kw in opt_text for kw in ['decline', 'prefer not', 'do not', 'not to say', 'not wish']):
                                opt.click()
                                decline_clicked = True
                                filled += 1
                                time.sleep(0.3)
                                break
                        if not decline_clicked:
                            # Just pick first option
                            first_opt = page.locator('[role="option"]').first
                            if first_opt.is_visible(timeout=500):
                                first_opt.click()
                                filled += 1
                                time.sleep(0.3)
                            else:
                                page.keyboard.press("Escape")
                    except Exception:
                        try:
                            page.keyboard.press("Escape")
                        except:
                            pass
                    continue
                
                # Fill the combobox: click → type → select option
                combo.click()
                time.sleep(0.3)
                combo.fill("")  # Clear any existing text
                time.sleep(0.2)
                page.keyboard.type(answer, delay=30)  # Type triggers React search
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
                else:
                    # Ensure dropdown is closed after successful selection
                    try:
                        page.keyboard.press("Escape")
                    except:
                        pass
                    
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
        
        # Fill Country combobox if still empty (fallback)
        try:
            country_combo = page.locator('#country').first
            if country_combo.is_visible(timeout=500):
                # Check if parent container shows a selected value
                parent_ctrl = country_combo.locator("xpath=ancestor::div[contains(@class,'select__control')]")
                has_value = parent_ctrl.locator('.select__single-value, [class*="singleValue"]').count() > 0
                if not has_value:
                    country_combo.click()
                    time.sleep(0.3)
                    country_combo.fill("United States")
                    time.sleep(0.5)
                    us_option = page.locator('[role="option"]').first
                    if us_option.is_visible(timeout=500):
                        us_option.click()
                        filled += 1
                        time.sleep(0.3)
        except Exception:
            pass
            
    except Exception:
        pass
    
    # Second pass: directly fill known EEO fields by ID if still empty
    EEO_FIXES = {
        "veteran_status": "I am not a protected",
        "disability_status": "I do not want to answer",
        "gender": "Decline To Self Identify",
        "hispanic_ethnicity": "No",
    }
    for eid, etext in EEO_FIXES.items():
        try:
            combo = page.locator(f"#{eid}")
            if not combo.is_visible(timeout=500):
                continue
            # Check if already filled
            try:
                vc = combo.locator("xpath=ancestor::div[contains(@class,'select__control')]//div[contains(@class,'single-value')]")
                if vc.count() > 0 and vc.first.inner_text(timeout=300).strip():
                    continue
            except:
                pass
            # Fill it
            combo.scroll_into_view_if_needed()
            time.sleep(0.2)
            combo.click()
            time.sleep(0.3)
            page.keyboard.type(etext, delay=30)
            time.sleep(0.8)
            opts = page.locator('[role="option"]:visible').all()
            if opts:
                opts[0].click()
                filled += 1
                time.sleep(0.3)
            page.keyboard.press("Escape")
        except:
            try:
                page.keyboard.press("Escape")
            except:
                pass

    if filled:
        print(f"      🔽 Filled {filled} Greenhouse custom dropdowns")
    
    return filled


def simulate_human_behavior(page) -> None:
    """Simulate human behavior to boost reCAPTCHA Enterprise score."""
    import random
    try:
        viewport = page.viewport_size or {"width": 1920, "height": 1080}
        for _ in range(random.randint(3, 6)):
            x = random.randint(100, viewport["width"] - 100)
            y = random.randint(100, viewport["height"] - 100)
            page.mouse.move(x, y, steps=random.randint(5, 15))
            time.sleep(random.uniform(0.1, 0.3))
        for _ in range(random.randint(2, 4)):
            page.mouse.wheel(0, random.randint(100, 300))
            time.sleep(random.uniform(0.3, 0.7))
        page.mouse.wheel(0, -500)
        time.sleep(random.uniform(0.5, 1.0))
    except Exception:
        pass


def solve_recaptcha_enterprise(page, url: str, override_sitekey: str = "") -> bool:
    """Handle reCAPTCHA Enterprise (invisible/score-based).
    
    Strategy:
    1. Try CapSolver API (paid, $0.80/1000 — but WORKS from CI datacenter IPs)
    2. Fallback: try grecaptcha.enterprise.execute() locally (only works with good browser score)
    3. If both fail: return False so caller can route to email outreach
    """
    import os, time, re as _re
    simulate_human_behavior(page)
    
    # Extract sitekey using comprehensive universal detector
    # Greenhouse loads reCAPTCHA Enterprise dynamically — need multiple approaches
    sitekey = page.evaluate("""() => {
        const results = [];
        
        // 1. data-sitekey attributes
        document.querySelectorAll('[data-sitekey]').forEach(el => {
            const key = el.getAttribute('data-sitekey');
            if (key && key !== 'explicit') results.push(key);
        });
        if (results.length) return results[0];
        
        // 2. Script src render= parameter
        document.querySelectorAll('script[src*="recaptcha"]').forEach(s => {
            try {
                const url = new URL(s.src);
                const render = url.searchParams.get('render');
                if (render && render !== 'explicit') results.push(render);
            } catch(e) {}
        });
        if (results.length) return results[0];
        
        // 3. iframe k= parameter
        document.querySelectorAll('iframe[src*="recaptcha"]').forEach(f => {
            try {
                const url = new URL(f.src);
                const k = url.searchParams.get('k');
                if (k) results.push(k);
            } catch(e) {}
        });
        if (results.length) return results[0];
        
        // 4. Search page source for grecaptcha.execute calls and render= URLs
        const html = document.documentElement.innerHTML;
        const patterns = [
            /grecaptcha(?:\.enterprise)?\.execute\s*\(\s*['"]([^'"]+)['"]/g,
            /(?:sitekey|siteKey|recaptchaSiteKey|recaptchaKey|googlekey)\s*[:=]\s*['"]([^'"]+)['"]/g,
            /recaptcha\/(?:api|enterprise)\.js\?[^"'<>]*render=([^&"'<>\s]+)/g,
        ];
        for (const pattern of patterns) {
            for (const match of html.matchAll(pattern)) {
                const key = decodeURIComponent(match[1]);
                if (key && key !== 'explicit' && key.length > 10 && key.length < 60) {
                    results.push(key);
                }
            }
        }
        if (results.length) return results[0];
        
        // 5. Performance resource entries (catches dynamically loaded scripts)
        try {
            const entries = performance.getEntriesByType('resource');
            for (const e of entries) {
                if (e.name && e.name.includes('recaptcha')) {
                    const m = e.name.match(/render=([^&]+)/);
                    if (m && m[1] !== 'explicit') { results.push(m[1]); break; }
                    const k = e.name.match(/[?&]k=([^&]+)/);
                    if (k) { results.push(k[1]); break; }
                }
            }
        } catch(e) {}
        if (results.length) return results[0];
        
        // 6. grecaptcha internal config
        try {
            if (typeof grecaptcha !== 'undefined') {
                const cfg = window.___grecaptcha_cfg;
                if (cfg && cfg.clients) {
                    for (const clientId of Object.keys(cfg.clients)) {
                        const client = cfg.clients[clientId];
                        // Walk the client object tree looking for sitekey-shaped strings
                        const walk = (obj, depth) => {
                            if (depth > 4 || !obj) return null;
                            if (typeof obj === 'string' && obj.length > 20 && obj.length < 50 && /^[A-Za-z0-9_-]+$/.test(obj)) {
                                return obj;
                            }
                            if (typeof obj === 'object') {
                                for (const key of Object.keys(obj)) {
                                    const found = walk(obj[key], depth + 1);
                                    if (found) return found;
                                }
                            }
                            return null;
                        };
                        const found = walk(client, 0);
                        if (found) { results.push(found); break; }
                    }
                }
            }
        } catch(e) {}
        if (results.length) return results[0];
        
        // 7. Global window variables
        const globals = ['__RECAPTCHA_SITE_KEY', '__recaptcha_site_key', 'RECAPTCHA_SITE_KEY', 
                        'recaptchaSiteKey', 'recaptchaKey', 'googleRecaptchaKey', 'publicKey'];
        for (const g of globals) {
            if (window[g] && typeof window[g] === 'string') return window[g];
        }
        
        return null;
    }""")
    
    # FALLBACK: If JS extraction failed, check Playwright's page URL history
    # The recaptcha script URL is: google.com/recaptcha/enterprise.js?render=SITEKEY
    if not sitekey:
        try:
            # Check all frames for recaptcha URLs
            for frame in page.frames:
                frame_url = frame.url
                if 'recaptcha' in frame_url:
                    m = _re.search(r'[?&]k=([^&]+)', frame_url)
                    if m:
                        sitekey = m.group(1)
                        print(f"      🔑 Found sitekey from frame URL: {sitekey[:12]}...")
                        break
        except Exception:
            pass
    
    # FALLBACK 2: Get ALL page script URLs from DOM including dynamically added
    if not sitekey:
        try:
            all_scripts = page.evaluate("""() => {
                return Array.from(document.querySelectorAll('script')).map(s => s.src).filter(Boolean);
            }""")
            for src in (all_scripts or []):
                if 'recaptcha' in src and 'render=' in src:
                    m = _re.search(r'render=([^&]+)', src)
                    if m and m.group(1) != 'explicit':
                        sitekey = m.group(1)
                        print(f"      🔑 Found sitekey from script list: {sitekey[:12]}...")
                        break
        except Exception:
            pass
    
    if sitekey:
        print(f"      🔑 reCAPTCHA Enterprise sitekey found: {sitekey[:15]}...")
    elif override_sitekey:
        sitekey = override_sitekey
        print(f"      🔑 reCAPTCHA Enterprise sitekey from network intercept: {sitekey[:15]}...")
    
    # === METHOD 1: CapSolver API (works from any IP, paid) ===
    # Dynamic disable: if CapSolver already failed this session (no balance), skip it
    capsolver_key = os.environ.get("CAPSOLVER_KEY", "")
    if hasattr(solve_recaptcha_enterprise, '_capsolver_disabled') and solve_recaptcha_enterprise._capsolver_disabled:
        capsolver_key = ""  # Skip — already know it has no balance
    if capsolver_key and sitekey:
        try:
            import requests as _req
            print(f"      🔑 Solving reCAPTCHA Enterprise via CapSolver (sitekey={sitekey[:12]}...)...")
            task_resp = _req.post("https://api.capsolver.com/createTask", json={
                "clientKey": capsolver_key,
                "task": {
                    "type": "ReCaptchaV3EnterpriseTaskProxyLess",
                    "websiteURL": url,
                    "websiteKey": sitekey,
                    "pageAction": "submit",
                }
            }, timeout=15).json()
            task_id = task_resp.get("taskId")
            if not task_id:
                error_code = task_resp.get("errorCode", "unknown")
                error_desc = task_resp.get("errorDescription", str(task_resp)[:150])
                print(f"      ⚠️ CapSolver rejected: {error_code} — {error_desc}")
                # If balance/key issue — disable for entire session (don't retry 40 times)
                if "DENIED" in error_code or "insufficient" in error_desc.lower() or "invalid" in error_desc.lower():
                    solve_recaptcha_enterprise._capsolver_disabled = True
                    print(f"      🚫 CapSolver DISABLED for this session (no balance/invalid key)")
                    print(f"         → Top up at https://dashboard.capsolver.com")
                # Try alternative task type if first one fails
                elif "type" in str(error_desc).lower() or "not support" in str(error_desc).lower():
                    print(f"      🔄 Retrying with ReCaptchaV3TaskProxyLess...")
                    task_resp = _req.post("https://api.capsolver.com/createTask", json={
                        "clientKey": capsolver_key,
                        "task": {
                            "type": "ReCaptchaV3TaskProxyLess",
                            "websiteURL": url,
                            "websiteKey": sitekey,
                            "pageAction": "submit",
                        }
                    }, timeout=15).json()
                    task_id = task_resp.get("taskId")
                    if not task_id:
                        print(f"      ⚠️ CapSolver retry also rejected: {task_resp.get('errorCode', '')} — {task_resp.get('errorDescription', '')[:100]}")
            if task_id:
                for _ in range(30):
                    time.sleep(2)
                    result = _req.post("https://api.capsolver.com/getTaskResult", json={
                        "clientKey": capsolver_key, "taskId": task_id
                    }, timeout=10).json()
                    if result.get("status") == "ready":
                        token = result["solution"].get("gRecaptchaResponse", "")
                        if token and len(token) > 20:
                            page.evaluate("""(token) => {
                                document.querySelectorAll('[name="g-recaptcha-response"], [name="recaptcha-token"], textarea[id*="recaptcha"]').forEach(el => { el.value = token; });
                                document.querySelectorAll('input[type="hidden"]').forEach(el => {
                                    if (el.name && (el.name.includes('captcha') || el.name.includes('recaptcha'))) el.value = token;
                                });
                            }""", token)
                            print(f"      ✅ reCAPTCHA Enterprise solved via CapSolver!")
                            return True
                        break
                    elif result.get("status") == "failed":
                        break
                print(f"      ⚠️ CapSolver failed — trying local execute")
        except Exception as e:
            print(f"      ⚠️ CapSolver error: {str(e)[:60]}")
    elif capsolver_key and not sitekey:
        # Sitekey not found immediately — wait for reCAPTCHA to load and retry
        print(f"      🔍 Sitekey not found — triggering reCAPTCHA load (scroll + wait 5s)...")
        # Trigger reCAPTCHA to load: scroll to bottom, hover submit button
        try:
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
            # Try hovering/focusing submit to trigger lazy reCAPTCHA
            try:
                submit_btn = page.locator('button[type="submit"], button:has-text("Submit"), input[type="submit"]').first
                if submit_btn.is_visible(timeout=1000):
                    submit_btn.hover()
            except Exception:
                pass
        except Exception:
            pass
        time.sleep(3)
        sitekey = page.evaluate("""() => {
            // Full re-scan after triggering load
            // Check script tags
            let sitekey = null;
            document.querySelectorAll('script[src*="recaptcha"]').forEach(s => {
                try {
                    const url = new URL(s.src);
                    const render = url.searchParams.get('render');
                    if (render && render !== 'explicit') sitekey = render;
                } catch(e) {}
            });
            if (sitekey) return sitekey;
            // Check iframes
            document.querySelectorAll('iframe[src*="recaptcha"]').forEach(f => {
                try {
                    const url = new URL(f.src);
                    const k = url.searchParams.get('k');
                    if (k) sitekey = k;
                } catch(e) {}
            });
            if (sitekey) return sitekey;
            // Check performance entries
            try {
                const entries = performance.getEntriesByType('resource');
                for (const e of entries) {
                    if (e.name && e.name.includes('recaptcha')) {
                        const m = e.name.match(/render=([^&]+)/);
                        if (m && m[1] !== 'explicit') return m[1];
                        const k = e.name.match(/[?&]k=([^&]+)/);
                        if (k) return k[1];
                    }
                }
            } catch(e) {}
            // Check full HTML source
            const html = document.documentElement.outerHTML;
            const m = html.match(/recaptcha[^"']*?render=([A-Za-z0-9_-]{20,})/);
            if (m) return m[1];
            // Check grecaptcha config
            try {
                if (window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients) {
                    for (const cid of Object.keys(window.___grecaptcha_cfg.clients)) {
                        const c = window.___grecaptcha_cfg.clients[cid];
                        const walk = (obj, d) => {
                            if (d > 3 || !obj) return null;
                            if (typeof obj === 'string' && obj.length > 20 && obj.length < 50 && /^[A-Za-z0-9_-]+$/.test(obj)) return obj;
                            if (typeof obj === 'object') { for (const k of Object.keys(obj)) { const f = walk(obj[k], d+1); if (f) return f; } }
                            return null;
                        };
                        const f = walk(c, 0);
                        if (f) return f;
                    }
                }
            } catch(e) {}
            return null;
        }""")
        if sitekey:
            try:
                import requests as _req
                print(f"      🔑 Solving reCAPTCHA Enterprise via CapSolver (sitekey={sitekey[:12]}...)...")
                task_resp = _req.post("https://api.capsolver.com/createTask", json={
                    "clientKey": capsolver_key,
                    "task": {
                        "type": "ReCaptchaV3EnterpriseTaskProxyLess",
                        "websiteURL": url,
                        "websiteKey": sitekey,
                        "pageAction": "submit",
                    }
                }, timeout=15).json()
                task_id = task_resp.get("taskId")
                if task_id:
                    for _ in range(30):
                        time.sleep(2)
                        result = _req.post("https://api.capsolver.com/getTaskResult", json={
                            "clientKey": capsolver_key, "taskId": task_id
                        }, timeout=10).json()
                        if result.get("status") == "ready":
                            token = result["solution"].get("gRecaptchaResponse", "")
                            if token and len(token) > 20:
                                page.evaluate("""(token) => {
                                    document.querySelectorAll('[name="g-recaptcha-response"], [name="recaptcha-token"], textarea[id*="recaptcha"]').forEach(el => { el.value = token; });
                                    document.querySelectorAll('input[type="hidden"]').forEach(el => {
                                        if (el.name && (el.name.includes('captcha') || el.name.includes('recaptcha'))) el.value = token;
                                    });
                                }""", token)
                                print(f"      ✅ reCAPTCHA Enterprise solved via CapSolver (retry)!")
                                return True
                            break
                        elif result.get("status") == "failed":
                            break
            except Exception as e:
                print(f"      ⚠️ CapSolver retry error: {str(e)[:60]}")
    
    # === METHOD 1.5: FREE token generation via anchor/reload (no API key needed) ===
    if sitekey:
        try:
            from urllib.request import urlopen, Request
            from urllib.parse import urlencode, urlparse
            import json as _json
            
            # Build the anchor URL (same as what browser requests from Google)
            parsed = urlparse(url)
            co_param = __import__('base64').b64encode(f"{parsed.scheme}://{parsed.netloc}:443".encode()).decode().rstrip('=')
            
            # Try Enterprise endpoint first, then standard
            for endpoint_base in ["enterprise", "api2"]:
                anchor_url = (
                    f"https://www.google.com/recaptcha/{endpoint_base}/anchor?"
                    f"ar=1&k={sitekey}&co={co_param}&hl=en&v=hfUOICODIRRlXBFLGaBAlq4A&size=invisible&cb=1"
                )
                try:
                    req = Request(anchor_url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"})
                    with urlopen(req, timeout=10) as resp:
                        anchor_html = resp.read().decode()
                    
                    # Extract recaptcha-token from anchor response
                    token_match = _re.search(r'id="recaptcha-token"\s*value="(.*?)"', anchor_html)
                    if not token_match:
                        continue
                    
                    recap_token = token_match.group(1)
                    
                    # POST to reload endpoint to get solved token
                    reload_data = urlencode({
                        "v": "hfUOICODIRRlXBFLGaBAlq4A",
                        "reason": "q",
                        "k": sitekey,
                        "c": recap_token,
                        "co": co_param,
                        "hl": "en",
                        "size": "invisible",
                        "chr": "",
                        "vh": "",
                        "bg": "",
                    }).encode()
                    
                    reload_url = f"https://www.google.com/recaptcha/{endpoint_base}/reload?k={sitekey}"
                    req2 = Request(reload_url, data=reload_data, headers={
                        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                        "Content-Type": "application/x-www-form-urlencoded",
                    })
                    with urlopen(req2, timeout=10) as resp2:
                        reload_response = resp2.read().decode()
                    
                    # Parse the token from reload response (format: )]}\n["rresp","TOKEN",...])
                    reload_json = _json.loads(reload_response.split('\n', 1)[-1] if '\n' in reload_response else reload_response[5:])
                    free_token = reload_json[1] if len(reload_json) > 1 else ""
                    
                    if free_token and len(free_token) > 20:
                        page.evaluate("""(token) => {
                            document.querySelectorAll('[name="g-recaptcha-response"], [name="recaptcha-token"], textarea[id*="recaptcha"]').forEach(el => { el.value = token; });
                            document.querySelectorAll('input[type="hidden"]').forEach(el => {
                                if (el.name && (el.name.includes('captcha') || el.name.includes('recaptcha'))) el.value = token;
                            });
                        }""", free_token)
                        print(f"      ✅ reCAPTCHA Enterprise solved FREE via {endpoint_base}/reload!")
                        return True
                except Exception:
                    continue
            
            print(f"      ⚠️ Free anchor/reload method failed — trying local execute")
        except Exception as e:
            print(f"      ⚠️ Free solver error: {str(e)[:80]}")
    
    # === METHOD 2: Local grecaptcha.enterprise.execute() (only works with high browser trust) ===
    try:
        token = page.evaluate("""() => {
            return new Promise((resolve) => {
                if (typeof grecaptcha === 'undefined' || !grecaptcha.enterprise) { resolve(null); return; }
                let sitekey = null;
                document.querySelectorAll('script[src*="recaptcha"]').forEach(s => {
                    const m = s.src.match(/render=([^&]+)/);
                    if (m && m[1] !== 'explicit') sitekey = m[1];
                });
                if (!sitekey) { const el = document.querySelector('[data-sitekey]'); if (el) sitekey = el.dataset.sitekey; }
                if (!sitekey) { resolve(null); return; }
                try {
                    grecaptcha.enterprise.ready(() => {
                        grecaptcha.enterprise.execute(sitekey, {action: 'submit'})
                            .then(token => resolve(token)).catch(() => resolve(null));
                    });
                } catch(e) { resolve(null); }
                setTimeout(() => resolve(null), 10000);
            });
        }""")
        if token and len(str(token)) > 20:
            page.evaluate("""(token) => {
                document.querySelectorAll('[name="g-recaptcha-response"], [name="recaptcha-token"], textarea[id*="recaptcha"]').forEach(el => { el.value = token; });
                document.querySelectorAll('input[type="hidden"]').forEach(el => {
                    if (el.name && (el.name.includes('captcha') || el.name.includes('recaptcha'))) el.value = token;
                });
            }""", token)
            print(f"      🔓 reCAPTCHA Enterprise token obtained (local — may have low score)")
            return True
    except Exception:
        pass
    
    # Both methods failed — return False so caller knows to skip/route to email
    # === METHOD 3: Gemini Flash visual CAPTCHA solver (FREE — 1000 solves/day) ===
    if solve_captcha_with_gemini:
        print(f"      🤖 Trying Gemini Flash visual solver (free fallback)...")
        if solve_captcha_with_gemini(page, "recaptcha"):
            return True
        print(f"      ⚠️ Gemini visual solver also failed")

    if not capsolver_key:
        print(f"      ❌ reCAPTCHA Enterprise: CAPSOLVER_KEY not set (add secret to repo)")
    elif not sitekey:
        print(f"      ❌ reCAPTCHA Enterprise: could not extract sitekey from page")
    else:
        print(f"      ❌ reCAPTCHA Enterprise: CapSolver + local execute + Gemini all failed")
    return False


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
