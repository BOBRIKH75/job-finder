"""Tests for job scout."""
from src.job_scout import match_skills, extract_rate, is_remote, is_c2c


def test_strong_match():
    desc = "Looking for Java Spring Boot developer with Kafka, Kubernetes, Docker, AWS, MongoDB experience."
    result = match_skills(desc)
    assert result["score"] >= 60
    assert "java" in result["matched"]
    assert "spring boot" in result["matched"]
    assert result["verdict"] in ("STRONG_MATCH", "GOOD_MATCH")


def test_weak_match():
    # Use a custom skill set that doesn't overlap with the description
    custom_skills = {"cobol", "fortran", "mainframe", "jcl", "cics"}
    desc = "Looking for a Python Django developer with React, PostgreSQL, and TensorFlow."
    result = match_skills(desc, skills=custom_skills)
    assert result["score"] < 50  # no overlap at all
    assert result["verdict"] in ("WEAK_MATCH", "PARTIAL_MATCH")


def test_extract_hourly_rate():
    assert extract_rate("Rate: $75/hr C2C") is not None
    assert extract_rate("$60-$90/hour") is not None
    assert extract_rate("No rate mentioned") is None


def test_extract_salary():
    assert extract_rate("$150,000/year") is not None


def test_is_remote():
    assert is_remote("This is a remote position")
    assert is_remote("Work from home available")
    assert not is_remote("Onsite in Denver, CO")


def test_is_c2c():
    assert is_c2c("C2C or W2 accepted")
    assert is_c2c("Corp-to-Corp contract")
    assert not is_c2c("Full-time permanent position")
