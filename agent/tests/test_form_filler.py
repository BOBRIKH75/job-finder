"""Tests for form filler."""
from src.form_filler import (
    match_field_to_profile, needs_manual_review, is_honeypot,
    can_automate_url, build_fill_plan, load_profile,
)


def test_field_matching():
    profile = {"first_name": "Bob", "last_name": "Rikh", "email": "bob@test.com"}
    assert match_field_to_profile("First Name", profile) == "Bob"
    assert match_field_to_profile("Email Address", profile) == "bob@test.com"
    assert match_field_to_profile("Favorite Color", profile) is None


def test_manual_review_detection():
    assert needs_manual_review("I agree to the non-compete agreement")
    assert needs_manual_review("Exclusivity clause applies")
    assert not needs_manual_review("I agree to the NDA")


def test_honeypot_detection():
    assert is_honeypot({"style": "display:none"})
    assert is_honeypot({"style": "visibility: hidden"})
    assert not is_honeypot({"style": "display:block"})
    assert not is_honeypot({"style": ""})


def test_can_automate_lever():
    ok, reason = can_automate_url("https://jobs.lever.co/acme/123")
    assert ok is True
    assert "lever" in reason


def test_can_automate_greenhouse():
    ok, reason = can_automate_url("https://boards.greenhouse.io/acme/jobs/123")
    assert ok is True
    assert "greenhouse" in reason


def test_build_fill_plan():
    profile = {"first_name": "Bob", "email": "bob@test.com"}
    fields = [
        {"label": "First Name", "selector": "#fname", "type": "text"},
        {"label": "Email", "selector": "#email", "type": "email"},
        {"label": "Cover Letter", "selector": "#cover", "type": "textarea"},
        {"label": "Hidden", "selector": "#trap", "type": "text", "style": "display:none"},
    ]
    plan = build_fill_plan(fields, profile)
    assert len(plan) == 3  # honeypot excluded
    assert plan[0]["value"] == "Bob"
    assert plan[1]["value"] == "bob@test.com"
    assert plan[2]["needs_llm"] is True  # cover letter needs LLM


def test_load_profile():
    p = load_profile()
    assert p["first_name"] == "Bob"
    assert len(p["skills"]) > 50
