"""Tests for ghost job filter."""
from src.ghost_filter import calculate_ghost_score


def test_fresh_real_job():
    score, signals = calculate_ghost_score(
        posted_days_ago=3, applicant_count=25, has_salary=True,
        description="Senior Java Developer at Acme Corp. Spring Boot, Kafka, Kubernetes. " * 5,
        has_named_contact=True,
    )
    assert score < 30, f"Fresh real job scored {score} (should be <30)"


def test_old_ghost_job():
    score, _ = calculate_ghost_score(
        posted_days_ago=90, applicant_count=600, has_salary=False,
        description="Great opportunity in a fast-paced environment for a team player rock star.",
        has_named_contact=False, is_repost=True,
    )
    assert score > 60, f"Ghost job scored {score} (should be >60)"


def test_repost_penalty():
    score_no_repost, _ = calculate_ghost_score(posted_days_ago=5, description="Java dev " * 30)
    score_repost, _ = calculate_ghost_score(posted_days_ago=5, description="Java dev " * 30, is_repost=True)
    assert score_repost > score_no_repost


def test_short_description_flagged():
    score, signals = calculate_ghost_score(description="Java developer needed.")
    vague = [s for s in signals if s.name == "vague_description"]
    assert vague[0].score > 0


def test_fake_urgency_detected():
    score, signals = calculate_ghost_score(
        description="Urgently hiring Java developer ASAP for immediate need. " * 5
    )
    urgency = [s for s in signals if s.name == "fake_urgency"]
    assert urgency[0].score > 0


def test_score_capped_at_100():
    score, _ = calculate_ghost_score(
        posted_days_ago=120, applicant_count=1000, has_salary=False,
        description="rock star ninja guru in fast-paced environment urgently hiring asap",
        has_named_contact=False, is_repost=True, easy_apply_only=True,
    )
    assert score <= 100
