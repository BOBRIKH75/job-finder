"""Shared test fixtures."""
import sqlite3, pytest
from src.memory import init_db


@pytest.fixture
def db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


@pytest.fixture
def sample_job():
    return {
        "title": "Senior Java Developer",
        "company": "Acme Corp",
        "description": "Looking for a senior Java developer with Spring Boot, Kafka, and Kubernetes experience. "
                       "Must have 10+ years experience. C2C or W2. Remote. $80/hr.",
        "url": "https://jobs.lever.co/acme/12345",
        "location": "Remote",
        "posted_days_ago": 3,
        "applicant_count": 45,
        "has_salary": True,
    }
