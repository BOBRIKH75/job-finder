"""Ghost job detection — scores jobs 0-100 for likelihood of being fake/stale."""
import re
from dataclasses import dataclass

VAGUE_PHRASES = [
    "fast-paced environment", "team player", "self-starter", "dynamic",
    "competitive salary", "great benefits", "exciting opportunity",
    "rock star", "ninja", "guru", "wear many hats",
]

URGENCY_PHRASES = ["urgently hiring", "immediate need", "asap", "start tomorrow"]


@dataclass
class GhostSignal:
    name: str
    score: float  # 0-20 per signal
    reason: str


def score_posting_age(days: int) -> GhostSignal:
    if days > 60:
        return GhostSignal("stale_posting", 20, f"Posted {days} days ago (>60)")
    if days > 30:
        return GhostSignal("stale_posting", 12, f"Posted {days} days ago (>30)")
    if days > 14:
        return GhostSignal("stale_posting", 5, f"Posted {days} days ago (>14)")
    return GhostSignal("stale_posting", 0, f"Fresh posting ({days} days)")


def score_applicant_count(count: int) -> GhostSignal:
    if count > 500:
        return GhostSignal("high_applicants", 15, f"{count} applicants (>500)")
    if count > 200:
        return GhostSignal("high_applicants", 8, f"{count} applicants (>200)")
    return GhostSignal("high_applicants", 0, f"{count} applicants")


def score_salary_disclosed(has_salary: bool) -> GhostSignal:
    if not has_salary:
        return GhostSignal("no_salary", 12, "No salary/rate disclosed")
    return GhostSignal("no_salary", 0, "Salary disclosed")


def score_description_quality(description: str) -> GhostSignal:
    words = description.split()
    if len(words) < 50:
        return GhostSignal("vague_description", 15, f"Very short description ({len(words)} words)")
    vague_count = sum(1 for p in VAGUE_PHRASES if p in description.lower())
    if vague_count >= 3:
        return GhostSignal("vague_description", 10, f"{vague_count} vague phrases found")
    return GhostSignal("vague_description", 0, "Description looks specific")


def score_named_contact(has_contact: bool) -> GhostSignal:
    if not has_contact:
        return GhostSignal("no_contact", 8, "No named hiring manager or recruiter")
    return GhostSignal("no_contact", 0, "Named contact found")


def score_repost(is_repost: bool) -> GhostSignal:
    if is_repost:
        return GhostSignal("repost", 10, "Job appears to be reposted")
    return GhostSignal("repost", 0, "Not a repost")


def score_easy_apply_only(easy_apply_only: bool) -> GhostSignal:
    if easy_apply_only:
        return GhostSignal("easy_apply_only", 5, "Easy Apply only — no direct application")
    return GhostSignal("easy_apply_only", 0, "Direct application available")


def score_fake_urgency(description: str) -> GhostSignal:
    urgency = sum(1 for p in URGENCY_PHRASES if p in description.lower())
    if urgency > 0:
        return GhostSignal("fake_urgency", 8, f"Fake urgency language detected")
    return GhostSignal("fake_urgency", 0, "No fake urgency")


def score_c2c_red_flags(description: str) -> GhostSignal:
    """C2C-specific: no end client named, no rate, no duration."""
    flags = 0
    lower = description.lower()
    if "major" in lower and ("client" in lower or "company" in lower) and not re.search(r'at\s+[A-Z][a-z]+', description):
        flags += 1
    if "bench" in lower or "marketing" in lower and "resume" in lower:
        flags += 1
    if flags > 0:
        return GhostSignal("c2c_red_flags", 10 * flags, f"{flags} C2C red flag(s)")
    return GhostSignal("c2c_red_flags", 0, "No C2C red flags")


def calculate_ghost_score(
    posted_days_ago: int = 0,
    applicant_count: int = 0,
    has_salary: bool = True,
    description: str = "",
    has_named_contact: bool = True,
    is_repost: bool = False,
    easy_apply_only: bool = False,
) -> tuple[int, list[GhostSignal]]:
    """Calculate ghost score 0-100. Higher = more likely ghost/fake."""
    signals = [
        score_posting_age(posted_days_ago),
        score_applicant_count(applicant_count),
        score_salary_disclosed(has_salary),
        score_description_quality(description),
        score_named_contact(has_named_contact),
        score_repost(is_repost),
        score_easy_apply_only(easy_apply_only),
        score_fake_urgency(description),
        score_c2c_red_flags(description),
    ]
    total = min(100, sum(s.score for s in signals))
    return int(total), signals
