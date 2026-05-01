"""Form filler — browser automation for job application forms."""
import json, os, random, asyncio
from pathlib import Path
from src.ats_detector import detect_ats, BLOCKED_ATS
from src.human_simulator import field_pause, generate_typing_events

PROFILE_PATH = Path(__file__).parent.parent / "config" / "profile.json"

# Fields that require manual human review — never auto-accept
MANUAL_REVIEW_PATTERNS = ["non-compete", "noncompete", "exclusivity", "liquidated damages"]

# Standard field mappings: label pattern → profile key
FIELD_MAP = {
    "first name": "first_name",
    "last name": "last_name",
    "email": "email",
    "phone": "phone",
    "city": "city",
    "state": "state",
    "zip": "zip",
    "country": "country",
    "linkedin": "linkedin",
    "github": "github",
}


def load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text())


def match_field_to_profile(label: str, profile: dict) -> str | None:
    """Match a form field label to a profile value."""
    lower = label.lower().strip()
    for pattern, key in FIELD_MAP.items():
        if pattern in lower:
            return profile.get(key)
    return None


def needs_manual_review(text: str) -> bool:
    """Check if text contains legal clauses requiring human review."""
    lower = text.lower()
    return any(p in lower for p in MANUAL_REVIEW_PATTERNS)


def is_honeypot(element_info: dict) -> bool:
    """Detect honeypot fields that bots shouldn't fill."""
    style = element_info.get("style", "")
    checks = ["display:none", "display: none", "visibility:hidden", "opacity:0", "height:0", "width:0"]
    return any(c in style.replace(" ", "") for c in [c.replace(" ", "") for c in checks])


def can_automate_url(url: str) -> tuple[bool, str]:
    """Check if a URL can be automated. Returns (can_automate, reason)."""
    result = detect_ats(url)
    if not result.can_automate:
        return False, f"{result.ats_type} is blocked (difficulty: {result.difficulty})"
    return True, f"{result.ats_type} detected (difficulty: {result.difficulty})"


def build_fill_plan(fields: list[dict], profile: dict) -> list[dict]:
    """Build a plan for filling form fields from profile data."""
    plan = []
    for field in fields:
        if is_honeypot(field):
            continue
        label = field.get("label", "")
        value = match_field_to_profile(label, profile)
        plan.append({
            "selector": field.get("selector", ""),
            "label": label,
            "type": field.get("type", "text"),
            "value": value,
            "source": "profile" if value else "unknown",
            "needs_llm": value is None,
        })
    return plan
