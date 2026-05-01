"""Job scout — multi-source job search and skill matching."""
import json, re
from pathlib import Path

PROFILE_PATH = Path(__file__).parent.parent / "config" / "profile.json"


def load_skills() -> set[str]:
    profile = json.loads(PROFILE_PATH.read_text())
    return {s.lower() for s in profile["skills"]}


def match_skills(job_description: str, skills: set[str] = None) -> dict:
    """Match job description against candidate skills."""
    skills = skills or load_skills()
    desc_lower = job_description.lower()
    # Tokenize description into potential skill phrases (1-3 word ngrams)
    words = re.findall(r'[a-z][a-z0-9/+#. -]+', desc_lower)
    desc_tokens = set(words)
    # Also check multi-word skills
    for skill in skills:
        if " " in skill and skill in desc_lower:
            desc_tokens.add(skill)

    matched = skills & desc_tokens
    # Also check substring matches for multi-word skills
    for skill in skills:
        if skill in desc_lower:
            matched.add(skill)

    missing = set()
    # Extract likely skill requirements from description
    tech_pattern = re.findall(r'\b(?:experience with|proficiency in|knowledge of|skills?:?)\s*([^.;]+)', desc_lower)
    for phrase in tech_pattern:
        tokens = [t.strip() for t in re.split(r'[,/&]', phrase)]
        for t in tokens:
            t = t.strip()
            if t and t not in skills and len(t) > 2 and not t.startswith(("and ", "or ", "the ")):
                missing.add(t)

    total_required = len(matched) + len(missing) if missing else len(matched)
    score = (len(matched) / max(total_required, 1)) * 100

    return {
        "matched": sorted(matched),
        "matched_count": len(matched),
        "missing": sorted(missing)[:10],  # top 10 gaps
        "score": round(min(score, 100), 1),
        "verdict": _verdict(score),
    }


def _verdict(score: float) -> str:
    if score >= 80:
        return "STRONG_MATCH"
    if score >= 60:
        return "GOOD_MATCH"
    if score >= 40:
        return "PARTIAL_MATCH"
    return "WEAK_MATCH"


def extract_rate(text: str) -> str | None:
    """Extract hourly rate or salary from job text."""
    patterns = [
        r'\$(\d{2,3})\s*/\s*(?:hr|hour)',
        r'\$(\d{2,3})\s*-\s*\$?(\d{2,3})\s*/\s*(?:hr|hour)',
        r'\$(\d{2,3}),?(\d{3})\s*(?:/\s*(?:yr|year|annually))?',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(0)
    return None


def is_remote(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in ["remote", "work from home", "wfh", "telecommute"])


def is_c2c(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in ["c2c", "corp-to-corp", "corp to corp", "1099", "independent contractor"])
