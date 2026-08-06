"""Tests for LinkedIn Recruiter Finder module."""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from linkedin_recruiter_finder import (
    guess_email, verify_domain_mx, is_usa_based, verify_email_smtp,
    find_and_verify_recruiters, search_recruiters_by_company, _company_to_domain,
)


def test_guess_email_patterns():
    """Test email pattern generation."""
    emails = guess_email("John", "Smith", "collabera.com")
    assert "john.smith@collabera.com" in emails
    assert "johnsmith@collabera.com" in emails
    assert "jsmith@collabera.com" in emails
    assert "john_smith@collabera.com" in emails
    assert "j.smith@collabera.com" in emails
    assert "smith.john@collabera.com" in emails
    assert "john@collabera.com" in emails
    assert len(emails) == 7


def test_guess_email_handles_whitespace():
    emails = guess_email(" Alice ", " Johnson ", "example.com")
    assert "alice.johnson@example.com" in emails


@patch("linkedin_recruiter_finder.dns.resolver.resolve")
def test_verify_domain_mx(mock_resolve):
    """Test MX record check with mocked DNS (avoids CI flakiness)."""
    # Valid domain returns MX records
    mock_resolve.return_value = [MagicMock()]
    assert verify_domain_mx("collabera.com") is True

    # Invalid domain raises NXDOMAIN
    mock_resolve.side_effect = Exception("NXDOMAIN")
    assert verify_domain_mx("thisisnotarealdomainxyz123456.com") is False


def test_is_usa_based():
    """Test USA location filtering."""
    # USA locations
    assert is_usa_based("Denver, CO") is True
    assert is_usa_based("New York, NY") is True
    assert is_usa_based("San Francisco, CA") is True
    assert is_usa_based("United States") is True
    assert is_usa_based("Remote") is True
    assert is_usa_based("Austin, TX") is True
    assert is_usa_based("Seattle, WA") is True
    assert is_usa_based("Chicago, IL") is True

    # Non-USA locations
    assert is_usa_based("Bangalore, India") is False
    assert is_usa_based("Hyderabad, India") is False
    assert is_usa_based("Mumbai") is False
    assert is_usa_based("London, UK") is False
    assert is_usa_based("Toronto, Canada") is False
    assert is_usa_based("Pune, India") is False

    # Edge cases
    assert is_usa_based("") is False
    assert is_usa_based(None) is False


def test_filter_fake_recruiters():
    """India-based recruiters should be filtered out."""
    assert is_usa_based("Noida, India") is False
    assert is_usa_based("Gurgaon, India") is False
    assert is_usa_based("Chennai") is False
    assert is_usa_based("Delhi, India") is False
    # But USA-based at Indian companies should pass
    assert is_usa_based("Dallas, TX") is True


def test_company_to_domain():
    """Test company name to domain mapping."""
    assert _company_to_domain("Collabera") == "collabera.com"
    assert _company_to_domain("TEKsystems") == "teksystems.com"
    assert _company_to_domain("Some New Corp") == "somenewcorp.com"


@patch("linkedin_recruiter_finder.search_recruiters_by_company")
@patch("linkedin_recruiter_finder.verify_email_smtp")
def test_full_pipeline_integration(mock_smtp, mock_search):
    """Full pipeline with mocked LinkedIn, real MX verification."""
    mock_search.return_value = [
        {"name": "Jane Doe", "company": "Collabera", "location": "Dallas, TX", "title": "Recruiter"},
        {"name": "Raj Kumar", "company": "Collabera", "location": "Hyderabad, India", "title": "Recruiter"},
    ]
    mock_smtp.return_value = True

    results = find_and_verify_recruiters(["Collabera"])

    # Should filter out India-based recruiter
    assert len(results) == 1
    assert results[0]["name"] == "Jane Doe"
    assert results[0]["location"] == "Dallas, TX"
    assert "@collabera.com" in results[0]["email"]
    # India recruiter filtered
    assert not any(r["name"] == "Raj Kumar" for r in results)


@patch("linkedin_recruiter_finder.search_recruiters_by_company")
def test_pipeline_skips_invalid_domains(mock_search):
    """Pipeline skips companies with no MX records."""
    mock_search.return_value = [
        {"name": "Test User", "company": "FakeCo", "location": "Denver, CO", "title": "Recruiter"},
    ]
    # thisisnotarealdomainxyz123456.com has no MX
    with patch("linkedin_recruiter_finder._company_to_domain", return_value="thisisnotarealdomainxyz123456.com"):
        results = find_and_verify_recruiters(["FakeCo"])
    assert len(results) == 0
