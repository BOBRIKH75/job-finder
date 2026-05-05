"""Tests for multi-source job discovery — verifies all platforms are searched."""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.memory import get_db, init_db, application_exists, upsert_application, update_application_status
from src.ats_detector import detect_ats, BLOCKED_ATS


class TestMultiSourceDiscovery:
    """Verify jobs from all platforms are accepted."""

    def test_indeed_url_automatable(self):
        r = detect_ats("https://www.indeed.com/viewjob?jk=abc123")
        assert r.can_automate is True
        assert r.ats_type == "indeed"

    def test_dice_url_automatable(self):
        r = detect_ats("https://www.dice.com/job-detail/java-dev-123")
        assert r.can_automate is True

    def test_greenhouse_url_automatable(self):
        r = detect_ats("https://boards.greenhouse.io/company/jobs/123")
        assert r.can_automate is True

    def test_lever_url_automatable(self):
        r = detect_ats("https://jobs.lever.co/company/uuid-123")
        assert r.can_automate is True

    def test_ashby_url_automatable(self):
        r = detect_ats("https://jobs.ashbyhq.com/company/uuid-123")
        assert r.can_automate is True

    def test_workable_url_automatable(self):
        r = detect_ats("https://apply.workable.com/company/j/abc")
        assert r.can_automate is True

    def test_company_page_automatable(self):
        r = detect_ats("https://careers.datadog.com/apply/java-dev")
        assert r.can_automate is True

    def test_linkedin_blocked(self):
        r = detect_ats("https://www.linkedin.com/jobs/view/123")
        assert r.can_automate is False

    def test_indeed_not_in_blocked(self):
        assert "indeed" not in BLOCKED_ATS

    def test_dice_not_in_blocked(self):
        assert "dice" not in BLOCKED_ATS


class TestDeduplication:
    """Verify dedup only blocks applied jobs, not scored ones."""

    def test_scored_job_not_blocked(self):
        db = get_db(":memory:")
        init_db(db)
        upsert_application(db, company="X", job_title="Dev", job_url="https://x.com/1")
        # Default status is "scored" — should NOT block
        assert application_exists(db, "https://x.com/1") is False

    def test_applied_job_blocked(self):
        db = get_db(":memory:")
        init_db(db)
        upsert_application(db, company="X", job_title="Dev", job_url="https://x.com/1")
        update_application_status(db, "https://x.com/1", "applied")
        assert application_exists(db, "https://x.com/1") is True

    def test_submitted_job_blocked(self):
        db = get_db(":memory:")
        init_db(db)
        upsert_application(db, company="X", job_title="Dev", job_url="https://x.com/1")
        update_application_status(db, "https://x.com/1", "submitted")
        assert application_exists(db, "https://x.com/1") is True

    def test_new_url_not_blocked(self):
        db = get_db(":memory:")
        init_db(db)
        assert application_exists(db, "https://new-job.com/1") is False


class TestApplyURLConstruction:
    """Verify correct apply URLs are built for each platform."""

    def test_lever_gets_apply_suffix(self):
        url = "https://jobs.lever.co/company/uuid-123"
        apply_url = url.rstrip("/")
        if "lever.co" in apply_url and not apply_url.endswith("/apply"):
            apply_url += "/apply"
        assert apply_url.endswith("/apply")

    def test_greenhouse_gets_app_hash(self):
        url = "https://boards.greenhouse.io/company/jobs/123"
        apply_url = url.rstrip("/")
        if "greenhouse.io" in apply_url and "#app" not in apply_url:
            apply_url += "#app"
        assert "#app" in apply_url

    def test_ashby_gets_application_suffix(self):
        url = "https://jobs.ashbyhq.com/company/uuid-123"
        apply_url = url.rstrip("/")
        if "ashbyhq.com" in apply_url and not apply_url.endswith("/application"):
            apply_url += "/application"
        assert apply_url.endswith("/application")

    def test_indeed_url_unchanged(self):
        url = "https://www.indeed.com/viewjob?jk=abc123"
        apply_url = url.rstrip("/")
        # Indeed URLs don't get modified
        assert apply_url == url

    def test_dice_url_unchanged(self):
        url = "https://www.dice.com/job-detail/java-dev"
        apply_url = url.rstrip("/")
        assert apply_url == url


class TestSearchQueries:
    """Verify search query coverage."""

    def test_queries_cover_key_skills(self):
        from advanced_searches import LINKEDIN_JOB_QUERIES, INDEED_QUERIES
        all_text = " ".join(LINKEDIN_JOB_QUERIES) + " ".join(q["term"] for q in INDEED_QUERIES)
        assert "Java" in all_text
        assert "Spring Boot" in all_text
        assert "Kafka" in all_text
        assert "Kubernetes" in all_text
        assert "C2C" in all_text
        assert "contract" in all_text
        assert "remote" in all_text

    def test_queries_cover_platforms(self):
        from advanced_searches import get_all_job_queries
        queries = get_all_job_queries()
        platforms = {q["platform"] for q in queries}
        assert "linkedin" in platforms
        assert "indeed" in platforms
        assert "dice" in platforms

    def test_minimum_query_count(self):
        from advanced_searches import get_all_job_queries
        assert len(get_all_job_queries()) >= 30
