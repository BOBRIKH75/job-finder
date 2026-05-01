"""Tests for ATS detector."""
from src.ats_detector import detect_ats, detect_ats_from_html


def test_lever_detected():
    r = detect_ats("https://jobs.lever.co/acme/12345")
    assert r.ats_type == "lever"
    assert r.difficulty == "easy"
    assert r.can_automate is True


def test_greenhouse_blocked():
    r = detect_ats("https://boards.greenhouse.io/company/jobs/123")
    assert r.ats_type == "greenhouse"
    assert r.can_automate is False


def test_workday_detected():
    r = detect_ats("https://acme.wd5.myworkdayjobs.com/en-US/careers/job/123")
    assert r.ats_type == "workday"
    assert r.difficulty == "medium"


def test_unknown_url():
    r = detect_ats("https://careers.randomcompany.com/apply/java-dev")
    assert r.ats_type == "unknown"
    assert r.can_automate is True


def test_html_detection():
    html = '<div class="lever-jobs-container"><a href="https://jobs.lever.co/x">Apply</a></div>'
    assert detect_ats_from_html(html) == "lever"


def test_linkedin_blocked():
    r = detect_ats("https://www.linkedin.com/jobs/view/12345")
    assert r.ats_type == "linkedin"
    assert r.can_automate is False
