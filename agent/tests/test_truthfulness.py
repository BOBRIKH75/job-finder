"""Quality gate: application answers must never claim skills/facts absent from profile.json."""
import json
import pathlib

import pytest

from src.question_answerer import _profile_answer, _safe_default, _is_unverified_skill_claim

PROFILE = json.loads((pathlib.Path(__file__).parents[1] / "config" / "profile.json").read_text())


def test_profile_work_auth_is_green_card_no_sponsorship():
    assert PROFILE["requires_sponsorship"] is False
    assert PROFILE["work_authorization"] is True
    assert "green card" in PROFILE["visa_status"].lower()


@pytest.mark.parametrize("q", [
    "How many years of experience do you have with Salesforce?",
    "Years of COBOL experience",
    "How many years of Python experience do you have?",
])
def test_unknown_skill_years_is_zero(q):
    assert "python" not in PROFILE["skills"]
    assert _profile_answer(q, "text", None, PROFILE) == "0"
    assert _safe_default(q, "text", None, PROFILE) == "0"


@pytest.mark.parametrize("q", [
    "How many years of Java experience do you have?",
    "How many years of Spring Boot experience?",
    "Total years of professional software development experience",
])
def test_known_or_generic_years_use_profile(q):
    assert _profile_answer(q, "text", None, PROFILE) == str(PROFILE["years_experience"])


def test_yes_no_experience_with_unknown_skill_is_no():
    q = "Do you have experience with SAP HANA?"
    assert _profile_answer(q, "radio", ["Yes", "No"], PROFILE) == "No"
    assert _safe_default(q, "radio", ["Yes", "No"], PROFILE) == "No"


def test_yes_no_experience_with_profile_skill_not_flagged():
    assert not _is_unverified_skill_claim("do you have experience with kafka?", PROFILE)


def test_relocation_and_sponsorship_and_citizenship_honest():
    assert _profile_answer("Are you willing to relocate?", "radio", ["Yes", "No"], PROFILE) == "No"
    assert _profile_answer("Will you require sponsorship?", "radio", ["Yes", "No"], PROFILE) == "No"
    assert _profile_answer("Are you a US citizen?", "radio", ["Yes", "No"], PROFILE) == "No"
    assert _profile_answer("Are you legally authorized to work in the US?", "radio", ["Yes", "No"], PROFILE) == "Yes"


def test_demographics_never_invented():
    for q in ("Gender", "Race", "Are you Hispanic or Latino?", "Sexual orientation"):
        a = (_profile_answer(q, "text", None, PROFILE) or "").lower()
        assert a not in ("male", "female", "white", "heterosexual")


def test_applier_smart_answers_do_not_invent_demographics():
    src = (pathlib.Path(__file__).parents[1] / "src" / "applier.py").read_text()
    for bad in ('"Male"', '"White"', '"Heterosexual"'):
        assert bad not in src
