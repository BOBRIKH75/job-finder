"""Option matching fixtures taken from Indeed run 42400290124 (stuck at 43%)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from option_matcher import parse_range, resolve_checkboxes, resolve_option  # noqa: E402

PROFILE = json.load(open(os.path.join(os.path.dirname(__file__), "..", "config", "profile.json")))
TF = ["True", "False"]
YN = ["Yes", "No"]


@pytest.mark.parametrize("q,opts,ans,expected", [
    ("Are you legally authorized to work in the United States?", TF, "Yes", "True"),
    ("Are you legally authorized to work in the United States?", YN, "Yes", "Yes"),
    ("Do you require visa sponsorship now or in the future?", YN, "Yes", "No"),
    ("Do you require sponsorship?", TF, "No", "False"),
    ("Do you have 15 years of experience with Rust?", YN, "10", "No"),
    ("Do you have 10 years of experience with Java?", YN, "10", "Yes"),
    ("Do you have 15 years of experience with Java?", YN, "10", "No"),
    ("Have you worked with containerization technologies?", TF, "True", "True"),
    ("Have you shipped any compiled language to a production environment?", TF, "True", "False"),
    ("Do you have experience designing and implementing quantum compilers?", TF, "True", "False"),
    ("This role is on-site at our Madison, Wisconsin office. Are you able to work on-site?", TF, "True", "False"),
    ("Will you be able to reliably commute to Springdale, AR?", YN, "Yes", "No"),
    ("Are you willing to relocate?", YN, "Yes", "No"),
    ("Are you a US citizen?", YN, "Yes", "No"),
    ("Are you a US citizen or eligible to work in the US?", YN, "Yes", "Yes"),
])
def test_boolean(q, opts, ans, expected):
    assert resolve_option(q, opts, ans, PROFILE) == expected


@pytest.mark.parametrize("q,opts,expected", [
    ("How many years of Java experience do you have?", ["0-1", "1-3", "3-5", "5+", "10+"], "10+"),
    ("How many years of experience with Fortran?", ["0-1", "1-3", "5+"], "0-1"),
    ("Years of experience with Spring Boot", ["Less than 1 year", "1-3 years", "3-5 years", "5-10 years", "More than 10 years"], "5-10 years"),
    ("What is your expected annual salary?", ["$80,000-$100,000", "$100,000-$130,000", "$150,000-$170,000", "$170,000+"], "$150,000-$170,000"),
    ("Expected hourly rate?", ["$40-$60", "$60-$80", "$80-$100"], "$60-$80"),
    ("What is your notice period?", ["Immediately", "2 weeks", "1 month"], "Immediately"),
])
def test_ranges(q, opts, expected):
    assert resolve_option(q, opts, "10", PROFILE) == expected


def test_no_truthful_option_returns_none():
    assert resolve_option("Rate your Haskell skills", ["Beginner", "Expert"], "10", PROFILE) is None


def test_long_sentence_options():
    opts = ["Yes, I will require sponsorship", "No, I will not require sponsorship"]
    assert resolve_option("Will you require sponsorship?", opts, "No", PROFILE) == opts[1]


def test_parse_range():
    assert parse_range("5+") == (5, float("inf"))
    assert parse_range("0-1") == (0, 1)
    assert parse_range("$80k-$100k") == (80000, 100000)


def test_checkbox_groups():
    assert resolve_checkboxes("Which do you know?", ["Java", "COBOL", "Kafka"], PROFILE) == ["Java", "Kafka"]
    assert resolve_checkboxes("Which?", ["COBOL", "None of the above"], PROFILE) == ["None of the above"]
    assert resolve_checkboxes("Which?", ["COBOL", "Fortran"], PROFILE) == []
