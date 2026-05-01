"""Tests for bridge between job-finder and ai-job-agent."""
import json
from src.bridge import import_jobs_from_finder, export_jobs_for_agent
import pandas as pd


def test_import_missing_file():
    jobs = import_jobs_from_finder("/tmp/nonexistent.json")
    assert jobs == []


def test_export_and_import(tmp_path):
    df = pd.DataFrame([
        {"title": "Java Dev", "company": "Acme", "job_url": "https://acme.com/j/1",
         "location": "Remote", "description": "Java Spring Boot Kafka", "score": 85,
         "is_c2c": True, "min_amount": 70, "max_amount": 90, "interval": "hourly", "site": "indeed"},
    ])
    path = str(tmp_path / "test_jobs.json")
    n = export_jobs_for_agent(df, path)
    assert n == 1

    jobs = import_jobs_from_finder(path)
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Java Dev"
    assert jobs[0]["company"] == "Acme"
    assert jobs[0]["is_c2c"] is True
