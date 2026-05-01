"""Tests for page doctor — format fixing, error detection, captcha detection."""
from src.page_doctor import fix_field_format


def test_phone_formatting():
    assert fix_field_format("Phone Number", "3472685917") == "(347) 268-5917"
    assert fix_field_format("Mobile", "13472685917") == "+1 (347) 268-5917"


def test_zip_formatting():
    assert fix_field_format("Zip Code", "80314") == "80314"
    assert fix_field_format("Postal Code", "80314-1234") == "80314"


def test_url_formatting():
    assert fix_field_format("LinkedIn URL", "linkedin.com/in/bob") == "https://linkedin.com/in/bob"
    assert fix_field_format("GitHub", "https://github.com/bob") == "https://github.com/bob"


def test_salary_formatting():
    assert fix_field_format("Expected Salary", "$150,000") == "150000"
    assert fix_field_format("Compensation", "$75/hr") == "75"


def test_passthrough():
    assert fix_field_format("Full Name", "Bob Rikh") == "Bob Rikh"
    assert fix_field_format("Email", "bob@test.com") == "bob@test.com"
