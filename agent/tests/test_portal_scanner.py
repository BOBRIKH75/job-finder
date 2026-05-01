"""Tests for company portal scanner."""
from src.portal_scanner import (
    matches_skills, load_companies, save_companies,
    SEED_LEVER, SEED_GREENHOUSE, SKILLS_FILTER,
)


def test_matches_java_skills():
    assert matches_skills("Senior Java Developer")
    assert matches_skills("Spring Boot Backend Engineer")
    assert matches_skills("Kafka Platform Engineer")
    assert matches_skills("", "microservices architecture with java")
    assert not matches_skills("Marketing Manager")
    assert not matches_skills("Sales Representative")


def test_seed_lists_not_empty():
    assert len(SEED_LEVER) > 20
    assert len(SEED_GREENHOUSE) > 20


def test_load_save_companies(tmp_path):
    import src.portal_scanner as ps
    original = ps.COMPANIES_FILE
    ps.COMPANIES_FILE = tmp_path / "companies.json"

    # First load returns seeds
    companies = load_companies()
    assert len(companies["lever"]) > 0
    assert len(companies["greenhouse"]) > 0

    # Add a discovered company
    companies["lever"].append("newcompany")
    companies["discovered"].append("lever:newcompany")
    save_companies(companies)

    # Reload and verify
    reloaded = load_companies()
    assert "newcompany" in reloaded["lever"]
    assert "lever:newcompany" in reloaded["discovered"]

    ps.COMPANIES_FILE = original


def test_skills_filter_keywords():
    assert "java" in SKILLS_FILTER
    assert "spring" in SKILLS_FILTER
    assert "kafka" in SKILLS_FILTER
    assert "backend" in SKILLS_FILTER
