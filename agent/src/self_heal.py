"""Deterministic error classifier and retry config for job application failures.

Design rules:
- No guessing: each error type maps to a known, tested fix strategy.
- No skipping unless the error is truly unrecoverable (job gone, already applied).
- Configurable: edit RETRY_CONFIG to tune retry counts / delays without touching pipeline code.

Usage:
    from src.self_heal import classify_error, get_retry_config, STRATEGY

    error_type = classify_error(error_msg)
    cfg = get_retry_config(error_type)
    if cfg["strategy"] == STRATEGY.SKIP:
        ...
    elif cfg["strategy"] == STRATEGY.RETRY_API:
        time.sleep(cfg["delay_s"])
        # retry submit_greenhouse_api(...)
"""

# ── Error pattern matching ────────────────────────────────────────────────────

# Ordered by priority — first match wins.
_ERROR_PATTERNS: list[tuple[str, list[str]]] = [
    # Definitive "not worth retrying" signals
    ("already_applied",  ["already applied", "duplicate application", "previously applied",
                          "already submitted"]),
    ("not_found",        ["404", "not found", "position closed", "job removed",
                          "no longer available", "job has been filled"]),
    # Transient — fix is just a wait + retry
    ("otp_timeout",      ["otp timeout", "no verification code", "code not received",
                          "email timeout", "verification email"]),
    ("captcha_failed",   ["recaptcha failed", "captcha failed", "challenge failed",
                          "bot detection"]),
    ("network_error",    ["connection error", "connection refused", "ssl error",
                          "network", "dns", "read timeout", "connect timeout"]),
    # Form / API errors — fix is to use browser Playwright path
    ("form_field",       ["required field", "field is required", "missing required",
                          "invalid field", "start date", "available cities"]),
    ("api_400",          ["http 400", "bad request", "http 422", "unprocessable entity",
                          "malformed"]),
    ("remix_context",    ["remixcontext", "cannot fetch job page", "parse error",
                          "cannot fetch"]),
]


def classify_error(error_msg: str) -> str:
    """Map an error string to a known type. Returns 'unknown' if nothing matches."""
    lower = error_msg.lower()
    for error_type, patterns in _ERROR_PATTERNS:
        if any(p in lower for p in patterns):
            return error_type
    return "unknown"


# ── Retry strategies ──────────────────────────────────────────────────────────

class STRATEGY:
    SKIP        = "skip"         # Job gone or already applied — do not retry
    RETRY_API   = "retry_api"    # Transient error — sleep + retry submit_greenhouse_api
    RETRY_OTP   = "retry_otp"    # OTP email slow — sleep longer + retry get_verification_code
    USE_BROWSER = "use_browser"  # API can't handle this form — queue for Playwright


# Default: configurable without touching pipeline code.
# Set max_retries=0 to disable retries for a strategy (USE_BROWSER is always "try once").
RETRY_CONFIG: dict[str, dict] = {
    "already_applied": {"strategy": STRATEGY.SKIP,        "max_retries": 0, "delay_s": 0},
    "not_found":       {"strategy": STRATEGY.SKIP,        "max_retries": 0, "delay_s": 0},
    "otp_timeout":     {"strategy": STRATEGY.RETRY_OTP,   "max_retries": 2, "delay_s": 45},
    "captcha_failed":  {"strategy": STRATEGY.RETRY_API,   "max_retries": 2, "delay_s": 8},
    "network_error":   {"strategy": STRATEGY.RETRY_API,   "max_retries": 3, "delay_s": 12},
    "form_field":      {"strategy": STRATEGY.USE_BROWSER, "max_retries": 0, "delay_s": 0},
    "api_400":         {"strategy": STRATEGY.USE_BROWSER, "max_retries": 0, "delay_s": 0},
    "remix_context":   {"strategy": STRATEGY.USE_BROWSER, "max_retries": 0, "delay_s": 0},
    "unknown":         {"strategy": STRATEGY.USE_BROWSER, "max_retries": 0, "delay_s": 0},
}


def get_retry_config(error_type: str) -> dict:
    return RETRY_CONFIG.get(error_type, RETRY_CONFIG["unknown"])
