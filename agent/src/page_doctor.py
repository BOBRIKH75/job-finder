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
    """Check if page has a CAPTCHA."""
    captcha_signals = ['recaptcha', 'captcha', 'hcaptcha', 'turnstile', 'challenge-form',
                       'g-recaptcha', 'cf-turnstile', 'h-captcha']
    try:
        html = page.content().lower()
        return any(s in html for s in captcha_signals)
    except Exception:
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
        if "phone" in lower and ("invalid" in lower or "format" in lower):
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

        # "Resume is required"
        if ("resume" in lower or "cv" in lower) and "required" in lower:
            resume = Path(__file__).parent.parent / "resume.pdf"
            if resume.exists():
                try:
                    page.locator('input[type="file"]').first.set_input_files(str(resume))
                    fixed += 1
                except Exception:
                    pass

    return fixed
