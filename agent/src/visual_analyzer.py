"""Visual analyzer — takes screenshot, sends to AI vision model to understand the page.

When the agent is stuck (can't find fields, can't understand the form),
it takes a screenshot and asks Gemini Vision: "What do you see? What should I fill?"

This is the last resort — most expensive but most powerful.
"""
import base64, json, os
import httpx

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

PROFILE_CONTEXT = """Candidate: Bob Rikh | Email: bobrikh75@gmail.com | Phone: 347-268-5917
Location: Parker, CO 80314 | Java Backend Developer, 10+ years
Green Card holder, no sponsorship | C2C contractor, $55-90/hr
LinkedIn: https://www.linkedin.com/in/bobrikh75/"""


def analyze_screenshot(screenshot_bytes: bytes, question: str) -> str | None:
    """Send screenshot to Gemini Vision and ask a question about it."""
    if not GEMINI_KEY:
        return None

    b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

    try:
        resp = httpx.post(
            f"{GEMINI_URL}?key={GEMINI_KEY}",
            json={
                "contents": [{
                    "parts": [
                        {"text": f"{PROFILE_CONTEXT}\n\n{question}"},
                        {"inline_data": {"mime_type": "image/png", "data": b64}},
                    ]
                }]
            },
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        pass
    return None


def analyze_form_screenshot(screenshot_bytes: bytes) -> list[dict]:
    """Ask AI to identify all form fields from a screenshot."""
    result = analyze_screenshot(screenshot_bytes,
        "Look at this job application form screenshot. "
        "List every visible form field with: what it asks for, what value Bob should enter. "
        "Return as JSON array: [{\"field\": \"description\", \"value\": \"what to type\"}]"
    )
    if result:
        try:
            # Extract JSON from response (may have markdown wrapping)
            json_match = result[result.find("["):result.rfind("]") + 1]
            return json.loads(json_match)
        except Exception:
            pass
    return []


def analyze_error_screenshot(screenshot_bytes: bytes) -> list[str]:
    """Ask AI to read error messages from a screenshot."""
    result = analyze_screenshot(screenshot_bytes,
        "Look at this screenshot of a job application form. "
        "Are there any error messages, red text, or validation warnings visible? "
        "List each error message exactly as shown. Return as JSON array of strings."
    )
    if result:
        try:
            json_match = result[result.find("["):result.rfind("]") + 1]
            return json.loads(json_match)
        except Exception:
            pass
    return []


def analyze_stuck_page(screenshot_bytes: bytes) -> str | None:
    """Ask AI what to do when the agent is completely stuck."""
    return analyze_screenshot(screenshot_bytes,
        "I'm an AI agent trying to fill this job application form but I'm stuck. "
        "Look at the screenshot and tell me: "
        "1. What page am I on? (application form, login page, error page, CAPTCHA?) "
        "2. What should I do next? (fill a field, click a button, scroll down, go back?) "
        "3. If there's a specific button or link I should click, describe it. "
        "Be specific and actionable."
    )


def visual_fill_attempt(page) -> dict:
    """Take screenshot, ask AI to identify fields, return fill instructions."""
    result = {"fields": [], "advice": None, "errors": []}

    try:
        screenshot = page.screenshot(full_page=True)
    except Exception:
        return result

    # Ask AI to identify form fields
    fields = analyze_form_screenshot(screenshot)
    if fields:
        result["fields"] = fields

    # Check for errors
    errors = analyze_error_screenshot(screenshot)
    if errors:
        result["errors"] = errors

    # If no fields found, ask for general advice
    if not fields and not errors:
        advice = analyze_stuck_page(screenshot)
        result["advice"] = advice

    return result
