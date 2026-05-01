"""Tests for self-learning browser applier."""
from src.applier import load_profile, FIELD_MAP, KNOWN_ANSWERS, load_learned, save_learned, match_field, match_answer


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


def test_known_answers():
    assert "authorized" in KNOWN_ANSWERS
    assert KNOWN_ANSWERS["sponsorship"] == "No"
    assert KNOWN_ANSWERS["start"] == "Immediately"


def test_match_field_by_label():
    assert match_field("Full Name", "", "", "") == "name"
    assert match_field("", "email", "", "") == "email"
    assert match_field("", "", "Enter phone number", "") == "phone"
    assert match_field("", "", "", "LinkedIn URL") == "linkedin"
    assert match_field("", "", "", "") is None


def test_match_answer():
    assert match_answer("Are you authorized to work in the US?") == "Yes"
    assert match_answer("Do you require visa sponsorship?") == "No"
    assert match_answer("What is your favorite color?") is None


def test_learned_persistence(tmp_path):
    import src.applier as applier
    original = applier.LEARNED_FILE
    applier.LEARNED_FILE = tmp_path / "learned.json"

    save_learned({"winning_selectors": {"lever.co": {"#name": "name"}}, "success_count": {"lever.co": 3}, "fail_reasons": {}})
    data = load_learned()
    assert data["success_count"]["lever.co"] == 3
    assert data["winning_selectors"]["lever.co"]["#name"] == "name"

    applier.LEARNED_FILE = original


def test_field_map_matches_profile():
    p = load_profile()
    for label, key in FIELD_MAP.items():
        assert key in p or key in ("company", "location"), f"Missing: {key}"
