"""Tests for browser applier — tests field detection and matching logic (no real browser)."""
from src.applier import load_profile, FIELD_MAP, LEVER_SELECTORS, KNOWN_ANSWERS, load_learned, save_learned


def test_load_profile():
    p = load_profile()
    assert p["name"] == "Bob Rikh"
    assert p["email"] == "bobrikh75@gmail.com"
    assert p["phone"] == "347-268-5917"


def test_field_map_covers_basics():
    assert "name" in FIELD_MAP
    assert "email" in FIELD_MAP
    assert "phone" in FIELD_MAP
    assert "linkedin" in FIELD_MAP


def test_lever_selectors():
    assert "name" in LEVER_SELECTORS
    assert "email" in LEVER_SELECTORS
    assert "resume" in LEVER_SELECTORS
    assert "submit" in LEVER_SELECTORS


def test_known_answers():
    assert "authorized to work" in KNOWN_ANSWERS
    assert KNOWN_ANSWERS["sponsorship"] == "No"


def test_learned_persistence(tmp_path):
    import src.applier as applier
    original = applier.LEARNED_FILE
    applier.LEARNED_FILE = tmp_path / "learned.json"

    save_learned({"successes": {"lever.co": 3}, "failures": {}, "selectors": {}})
    data = load_learned()
    assert data["successes"]["lever.co"] == 3

    applier.LEARNED_FILE = original


def test_field_map_matches_profile_keys():
    p = load_profile()
    for label, key in FIELD_MAP.items():
        assert key in p or key in ("company", "location"), f"Profile missing key: {key}"
