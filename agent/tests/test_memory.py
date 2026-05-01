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
