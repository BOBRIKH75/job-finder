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


# --- Company rotation (fixes "same companies every run") ---

def test_rotate_returns_correct_slice():
    from src.portal_scanner import _rotate
    items = list("ABCDEFGHIJ")  # 10 items
    assert _rotate(items, 0, 3) == ["A", "B", "C"]
    assert _rotate(items, 3, 3) == ["D", "E", "F"]


def test_rotate_wraps_around_end():
    from src.portal_scanner import _rotate
    items = list("ABCDEFGHIJ")  # 10 items
    # Start near the end -> wraps back to the beginning
    assert _rotate(items, 8, 4) == ["I", "J", "A", "B"]


def test_rotate_offset_beyond_length_wraps():
    from src.portal_scanner import _rotate
    items = list("ABCDE")
    assert _rotate(items, 7, 2) == ["C", "D"]  # 7 % 5 = 2


def test_rotate_covers_whole_list_over_runs():
    from src.portal_scanner import _rotate
    items = list(range(95))  # ~ greenhouse list size
    batch = 30
    seen = set()
    offset = 0
    for _ in range(4):  # 4 runs
        seen.update(_rotate(items, offset, batch))
        offset = (offset + batch) % len(items)
    # 4 runs of 30 (with wrap) must cover the ENTIRE list
    assert seen == set(items)


def test_rotate_empty_list_safe():
    from src.portal_scanner import _rotate
    assert _rotate([], 0, 5) == []


def test_scan_offset_persist(tmp_path):
    import src.portal_scanner as ps
    original = ps._SCAN_STATE_FILE
    ps._SCAN_STATE_FILE = tmp_path / "scan_offset.json"
    try:
        assert ps._load_scan_offset() == 0  # default when missing
        ps._save_scan_offset(30)
        assert ps._load_scan_offset() == 30
    finally:
        ps._SCAN_STATE_FILE = original
