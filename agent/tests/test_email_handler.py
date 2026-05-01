"""Tests for email handler."""
from src.email_handler import should_follow_up, render_template, EmailThrottle
from datetime import datetime, timedelta


def test_follow_up_day_3():
    three_days_ago = (datetime.now() - timedelta(days=3)).isoformat()
    assert should_follow_up(three_days_ago) == 1


def test_follow_up_day_7():
    seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
    assert should_follow_up(seven_days_ago) == 2


def test_no_follow_up_too_early():
    yesterday = (datetime.now() - timedelta(days=1)).isoformat()
    assert should_follow_up(yesterday) is None


def test_render_template():
    t = "Hi {recruiter_name}, I saw {job_title} at {company}."
    result = render_template(t, recruiter_name="Alice", job_title="Java Dev", company="Acme")
    assert result == "Hi Alice, I saw Java Dev at Acme."


def test_throttle_limits():
    throttle = EmailThrottle(max_per_day=3)
    assert throttle.can_send()
    assert throttle.remaining == 3
    throttle.record_send()
    throttle.record_send()
    throttle.record_send()
    assert not throttle.can_send()
    assert throttle.remaining == 0


def test_throttle_none_contacted():
    assert should_follow_up(None) is None
