import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.gh_reconcile import confirmed_for, parse_confirmation_subject  # noqa: E402


def test_parse_thank_you():
    assert parse_confirmation_subject("Thank you for applying to Coinbase") == "Coinbase"
    assert parse_confirmation_subject("Your application to Airbnb") == "Airbnb"


def test_security_code_and_rejection_are_not_confirmations():
    assert parse_confirmation_subject("Security code for your application to Affirm") is None
    assert parse_confirmation_subject("Update on your application to Acme") is None


def test_confirmed_for_loose_match():
    conf = [{"what": "DoorDash", "subject": "Thank you for applying to DoorDash"}]
    assert confirmed_for("doordashusa", conf)
    assert not confirmed_for("lyft", conf)
