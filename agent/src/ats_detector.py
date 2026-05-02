"""ATS detector — identifies which Applicant Tracking System a job URL uses."""
import re
from dataclasses import dataclass
from urllib.parse import urlparse

# Difficulty: easy=agent can handle, medium=slow/careful, hard=manual only
ATS_SIGNATURES = {
    "lever": {
        "patterns": [r"jobs\.lever\.co", r"lever\.co/", r"api\.lever\.co"],
        "difficulty": "easy",
        "has_api": True,
    },
    "greenhouse": {
        "patterns": [r"boards\.greenhouse\.io", r"greenhouse\.io/"],
        "difficulty": "hard",  # reCAPTCHA Enterprise
        "has_api": True,
    },
    "workday": {
        "patterns": [r"myworkdayjobs\.com", r"\.wd\d+\.myworkdayjobs"],
        "difficulty": "medium",  # complex forms but no CAPTCHA
        "has_api": False,
    },
    "icims": {
        "patterns": [r"icims\.com", r"\.icims\."],
        "difficulty": "hard",  # CAPTCHA + session timeouts
        "has_api": False,
    },
    "taleo": {
        "patterns": [r"taleo\.net", r"oracle\.com/.*taleo"],
        "difficulty": "medium",
        "has_api": False,
    },
    "smartrecruiters": {
        "patterns": [r"smartrecruiters\.com", r"jobs\.smartrecruiters"],
        "difficulty": "hard",  # DataDome
        "has_api": True,
    },
    "bamboohr": {
        "patterns": [r"bamboohr\.com"],
        "difficulty": "easy",
        "has_api": False,
    },
    "ashby": {
        "patterns": [r"ashbyhq\.com", r"jobs\.ashby\.io"],
        "difficulty": "easy",
        "has_api": False,
    },
    "indeed": {
        "patterns": [r"indeed\.com"],
        "difficulty": "medium",
        "has_api": False,
    },
    "dice": {
        "patterns": [r"dice\.com"],
        "difficulty": "easy",
        "has_api": True,
    },
    "linkedin": {
        "patterns": [r"linkedin\.com/jobs"],
        "difficulty": "hard",  # aggressive bot detection
        "has_api": False,
    },
}

BLOCKED_ATS = {"icims", "linkedin", "smartrecruiters"}


@dataclass
class ATSResult:
    ats_type: str  # "lever", "workday", etc. or "unknown"
    difficulty: str  # "easy", "medium", "hard"
    has_api: bool
    can_automate: bool  # False if in BLOCKED_ATS
    domain: str


def detect_ats(url: str) -> ATSResult:
    """Detect which ATS a job URL uses."""
    domain = urlparse(url).netloc.lower()
    for ats_type, info in ATS_SIGNATURES.items():
        for pattern in info["patterns"]:
            if re.search(pattern, url, re.IGNORECASE):
                return ATSResult(
                    ats_type=ats_type,
                    difficulty=info["difficulty"],
                    has_api=info["has_api"],
                    can_automate=ats_type not in BLOCKED_ATS,
                    domain=domain,
                )
    return ATSResult(
        ats_type="unknown",
        difficulty="medium",
        has_api=False,
        can_automate=True,  # unknown sites get attempted
        domain=domain,
    )


def detect_ats_from_html(html: str) -> str | None:
    """Detect ATS from page HTML content (for company career pages)."""
    lower = html.lower()
    checks = [
        ("lever", ["lever.co", "lever-jobs-container"]),
        ("greenhouse", ["greenhouse.io", "gh_jid"]),
        ("workday", ["myworkdayjobs", "workday"]),
        ("icims", ["icims.com", "icims"]),
        ("ashby", ["ashbyhq.com", "ashby"]),
        ("bamboohr", ["bamboohr.com"]),
        ("smartrecruiters", ["smartrecruiters.com"]),
    ]
    for ats, keywords in checks:
        if any(kw in lower for kw in keywords):
            return ats
    return None
