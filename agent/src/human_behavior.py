"""Human-like browser behavior to avoid bot detection on job boards.

Key rules (2025 research):
- patchright beats playwright-stealth — patches Chromium binary, not JS layer
- Fixed user-agent = instant bot signal — rotate per session
- Fixed viewport = bot signal — randomize
- page.fill() is instant — type char-by-char with variable delay
- Bots click without hovering — always hover first
- Rate limits: LinkedIn 50/day, Indeed 40/day, Dice 50/day
- Never apply between midnight–6 AM local time
- Space applications 3–8 min apart minimum
"""

import random
import time

# ── Playwright module: patchright > playwright ────────────────────────────────

def get_playwright_module():
    """Return patchright.sync_playwright if installed, else playwright fallback."""
    try:
        from patchright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        from playwright.sync_api import sync_playwright
        return sync_playwright


# ── Randomized browser context args ──────────────────────────────────────────

# Realistic Mac + Chrome combos (2025). Never use Linux UA on Mac runner.
_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.127 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_VIEWPORTS = [
    {"width": 1440, "height": 900},
    {"width": 1440, "height": 810},
    {"width": 1680, "height": 1050},
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 2560, "height": 1440},
]

def random_context_args() -> dict:
    """Return randomized context kwargs — call once per browser session."""
    return {
        "user_agent": random.choice(_USER_AGENTS),
        "viewport": random.choice(_VIEWPORTS),
        "locale": "en-US",
        "timezone_id": "America/Denver",     # matches your residential IP
        "geolocation": {"latitude": 39.55, "longitude": -105.78},  # Denver
        "permissions": ["geolocation"],
        "color_scheme": "light",
        "device_scale_factor": random.choice([1.0, 2.0]),
        "extra_http_headers": {
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
        },
    }


# ── Human-like interactions ───────────────────────────────────────────────────

def human_type(page, selector: str, text: str, clear_first: bool = True):
    """Type text character by character with variable keystroke delay (50–180 ms).

    Much harder to detect than page.fill() which fires instantly.
    """
    locator = page.locator(selector).first
    if clear_first:
        locator.triple_click()   # select all
        page.keyboard.press("Backspace")
    for char in text:
        page.keyboard.type(char)
        time.sleep(random.uniform(0.05, 0.18))
    time.sleep(random.uniform(0.1, 0.4))  # pause after finishing field


def human_click(page, selector: str):
    """Hover over element, pause, then click — mimics human mouse movement."""
    locator = page.locator(selector).first
    locator.hover()
    time.sleep(random.uniform(0.25, 0.85))
    locator.click()
    time.sleep(random.uniform(0.4, 1.2))


def human_scroll(page, steps: int = None):
    """Scroll down the page in realistic chunks."""
    if steps is None:
        steps = random.randint(2, 5)
    for _ in range(steps):
        page.mouse.wheel(0, random.randint(200, 600))
        time.sleep(random.uniform(0.3, 1.0))


# Platforms with behavioral typing analysis — need char-by-char input.
# ATS platforms (Greenhouse, Lever, Ashby) only have reCAPTCHA, not typing analysis.
_SLOW_PLATFORMS = {"linkedin.com", "indeed.com", "dice.com", "ziprecruiter.com"}
_ATS_PLATFORMS  = {"greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
                   "jobvite.com", "icims.com", "myworkdayjobs.com"}


def smart_fill(page, selector: str, text: str, domain: str = "") -> bool:
    """Fill a form field — human_type for watched platforms, fast fill for ATS.

    Performance rationale:
      - LinkedIn/Indeed analyze typing speed — char-by-char needed (50-180ms/char)
      - Greenhouse/Lever only have reCAPTCHA — instant fill is fine, saves ~5s per field
      - A 50-char field on LinkedIn: ~5s  |  on Greenhouse: ~0.1s
      - With 10 fields per form × 30 jobs: saves up to 25 minutes per run

    Returns True on success, False on error (never raises).
    """
    try:
        if any(p in domain for p in _SLOW_PLATFORMS):
            human_type(page, selector, str(text))
        else:
            page.locator(selector).fill(str(text))
            time.sleep(random.uniform(0.08, 0.20))  # tiny pause — looks natural
        return True
    except Exception:
        return False


def between_applications_delay(domain: str = ""):
    """Platform-aware delay between job applications.

    LinkedIn/Indeed have behavioral analysis — need 3-8 min gap.
    Greenhouse/Lever only check reCAPTCHA — 15-45s is enough and maximizes throughput.
    """
    if "linkedin" in domain:
        delay = random.uniform(180, 480)   # 3–8 min
    elif "indeed" in domain:
        delay = random.uniform(60, 180)    # 1–3 min
    elif "dice" in domain:
        delay = random.uniform(45, 120)    # 45s–2 min
    elif any(p in domain for p in _ATS_PLATFORMS):
        delay = random.uniform(15, 45)     # 15–45s — reCAPTCHA is the only gate
    else:
        delay = random.uniform(20, 60)     # safe default for unknown platforms
    print(f"  ⏳ Inter-app delay ({domain or 'default'}): {int(delay)}s")
    time.sleep(delay)


# ── Daily rate limits ─────────────────────────────────────────────────────────

DAILY_LIMITS = {
    "linkedin.com":   50,
    "indeed.com":     40,
    "dice.com":       50,
    "greenhouse.io":  999,  # no published limit — reCAPTCHA is the only gate
    "lever.co":       999,
    "default":        40,
}

def get_daily_limit(domain: str) -> int:
    for key, limit in DAILY_LIMITS.items():
        if key in domain:
            return limit
    return DAILY_LIMITS["default"]


# ── Safe hours check ──────────────────────────────────────────────────────────

def is_safe_hours() -> bool:
    """Return True if current local hour is between 7 AM and 11 PM.

    Bots run 24/7 — humans don't apply at 3 AM. GitHub Actions cron fires at
    9 PM MT which is safe. This is a safety net in case someone triggers manually.
    """
    import datetime
    hour = datetime.datetime.now().hour  # local time on Mac runner (MT)
    return 7 <= hour <= 23
