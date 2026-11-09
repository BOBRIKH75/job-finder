import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.cv_match import should_apply


def test_denver_onsite_java_is_kept():
    ok, _, _ = should_apply("Java Developer", "Spring Boot microservices, on-site", "Denver, CO")
    assert ok


def test_onsite_outside_colorado_is_skipped():
    ok, _, why = should_apply("Java Developer", "Spring Boot, hybrid 3 days in office", "Seattle, WA")
    assert not ok and any("outside Colorado" in w for w in why)


def test_remote_job_anywhere_is_kept():
    ok, _, _ = should_apply("Java Developer", "Spring Boot, fully remote", "Seattle, WA")
    assert ok


def test_blank_location_never_blocks():
    ok, _, _ = should_apply("Senior Java Developer", "", "")
    assert ok
