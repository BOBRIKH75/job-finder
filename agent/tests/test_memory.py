"""Tests for memory module."""
import sqlite3, pytest
from src.memory import (
    init_db, upsert_application, get_applications, update_application_status,
    application_exists, upsert_recruiter, get_recruiter, get_approved_answer,
    save_approved_answer, audit, verify_audit_chain, get_stats,
)


@pytest.fixture
def db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def test_upsert_and_get_application(db):
    upsert_application(db, company="Acme", job_title="Java Dev", job_url="https://acme.com/j/1")
    apps = get_applications(db)
    assert len(apps) == 1
    assert apps[0]["company"] == "Acme"


def test_application_exists(db):
    assert not application_exists(db, "https://x.com/j/1")
    upsert_application(db, company="X", job_title="Dev", job_url="https://x.com/j/1")
    # Scored-only jobs should NOT block re-processing
    assert not application_exists(db, "https://x.com/j/1")
    # Applied jobs SHOULD block
    update_application_status(db, "https://x.com/j/1", "applied")
    assert application_exists(db, "https://x.com/j/1")


def test_update_status(db):
    upsert_application(db, company="A", job_title="B", job_url="https://a.com/1")
    update_application_status(db, "https://a.com/1", "applied")
    apps = get_applications(db, status="applied")
    assert len(apps) == 1


def test_recruiter_upsert_dedup(db):
    upsert_recruiter(db, "r@co.com", name="R1", company="Co")
    upsert_recruiter(db, "r@co.com", name="R1 Updated")
    rec = get_recruiter(db, "r@co.com")
    assert rec["name"] == "R1 Updated"


def test_seeded_approved_answers(db):
    ans = get_approved_answer(db, "Are you authorized to work in the United States?")
    assert ans == "Yes"
    ans2 = get_approved_answer(db, "Will you now or in the future require sponsorship?")
    assert ans2 == "No"


def test_save_and_get_approved_answer(db):
    save_approved_answer(db, "What is your rate?", "$75/hr C2C")
    assert get_approved_answer(db, "What is your rate?") == "$75/hr C2C"


def test_audit_log_chain(db):
    audit(db, "TEST_1", {"key": "val1"})
    audit(db, "TEST_2", {"key": "val2"})
    audit(db, "TEST_3")
    assert verify_audit_chain(db)


def test_stats(db):
    upsert_application(db, company="A", job_title="J", job_url="https://a.com/1", status="applied")
    upsert_application(db, company="B", job_title="J", job_url="https://b.com/1", status="found")
    s = get_stats(db)
    assert s["applied"] == 1
    assert s["found"] == 1
    assert s["total"] == 2


# --- URL normalization + cross-run dedup (fixes "applies to same job repeatedly") ---

def test_normalize_strips_tracking_params():
    from src.memory import normalize_job_url
    a = normalize_job_url("https://boards.greenhouse.io/affirm/jobs/123?gh_jid=456&utm_source=x")
    b = normalize_job_url("https://boards.greenhouse.io/affirm/jobs/123")
    assert a == b


def test_normalize_collapses_host_prefix():
    from src.memory import normalize_job_url
    a = normalize_job_url("https://job-boards.greenhouse.io/affirm/jobs/123")
    b = normalize_job_url("https://boards.greenhouse.io/affirm/jobs/123")
    assert a == b


def test_normalize_strips_www_and_trailing_slash():
    from src.memory import normalize_job_url
    a = normalize_job_url("https://www.dice.com/job/abc/")
    b = normalize_job_url("https://dice.com/job/abc")
    assert a == b


def test_same_job_different_tracking_url_is_deduped(db):
    # Applied once with tracking params
    upsert_application(db, company="Affirm", job_title="Java Dev",
                       job_url="https://boards.greenhouse.io/affirm/jobs/123?gh_jid=456")
    update_application_status(db, "https://boards.greenhouse.io/affirm/jobs/123?gh_jid=456", "applied")
    # Re-scraped later with DIFFERENT tracking params — must be recognized as applied
    assert application_exists(db, "https://boards.greenhouse.io/affirm/jobs/123?utm_source=google") is True


def test_role_fallback_dedup_when_url_differs(db):
    upsert_application(db, company="Acme", job_title="Senior Java Engineer",
                       job_url="https://acme.com/apply/1")
    update_application_status(db, "https://acme.com/apply/1", "applied")
    # Totally different URL but SAME company + title -> should be deduped via fallback
    assert application_exists(db, "https://linkedin.com/jobs/view/999",
                              company="Acme", title="Senior Java Engineer") is True


def test_role_fallback_does_not_overblock_different_role(db):
    upsert_application(db, company="Acme", job_title="Senior Java Engineer",
                       job_url="https://acme.com/apply/1")
    update_application_status(db, "https://acme.com/apply/1", "applied")
    # Different title at same company -> NOT deduped
    assert application_exists(db, "https://acme.com/apply/2",
                              company="Acme", title="DevOps Engineer") is False


def test_applied_via_email_also_blocks(db):
    upsert_application(db, company="X", job_title="Dev", job_url="https://x.com/e/1")
    update_application_status(db, "https://x.com/e/1", "applied_via_email")
    assert application_exists(db, "https://x.com/e/1") is True
