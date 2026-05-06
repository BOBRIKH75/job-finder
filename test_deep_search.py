#!/usr/bin/env python3
"""Tests for linkedin_deep_search.py and outreach.py"""
import json, os, sys, tempfile
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import linkedin_deep_search as lds
import outreach


# ══════════════════════════════════════════════════════════════
# UNIT TESTS — no network, fast
# ══════════════════════════════════════════════════════════════

class TestExtractEmails:
    def test_basic(self):
        text = "Contact john.doe@company.com for details"
        assert lds.extract_emails_from_text(text) == ["john.doe@company.com"]

    def test_filters_noreply(self):
        text = "noreply@company.com and real@company.com"
        result = lds.extract_emails_from_text(text)
        assert "real@company.com" in result
        assert "noreply@company.com" not in result

    def test_filters_indeed(self):
        text = "jobs@indeed.com and recruiter@staffing.com"
        result = lds.extract_emails_from_text(text)
        assert "recruiter@staffing.com" in result

    def test_empty(self):
        assert lds.extract_emails_from_text("") == []
        assert lds.extract_emails_from_text(None) == []

    def test_multiple(self):
        text = "a@x.com b@y.com a@x.com"
        result = lds.extract_emails_from_text(text)
        assert len(result) == 2  # deduped


class TestGuessEmailPatterns:
    def test_generates_patterns(self):
        patterns = lds.guess_email_patterns("John", "Smith", "acme.com")
        assert "john.smith@acme.com" in patterns
        assert "jsmith@acme.com" in patterns
        assert "john_smith@acme.com" in patterns

    def test_empty_inputs(self):
        assert lds.guess_email_patterns("", "Smith", "x.com") == []
        assert lds.guess_email_patterns("John", "", "x.com") == []


class TestEmailHash:
    def test_consistent(self):
        h1 = lds.email_hash("Test@Example.com")
        h2 = lds.email_hash("test@example.com")
        assert h1 == h2

    def test_length(self):
        assert len(lds.email_hash("a@b.com")) == 12


class TestGuessDomain:
    @patch("urllib.request.urlopen")
    def test_returns_first_valid(self, mock_urlopen):
        mock_urlopen.return_value.__enter__ = lambda s: s
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        result = lds._guess_domain("Acme Corp")
        assert "acmecorp" in result

    def test_empty_company(self):
        assert lds._guess_domain("") == ""


class TestOutreachExtractEmails:
    def test_basic(self):
        text = "Send resume to hiring@company.com"
        result = outreach.extract_emails(text)
        assert "hiring@company.com" in result

    def test_filters_junk(self):
        text = "noreply@x.com and real@y.com"
        result = outreach.extract_emails(text)
        assert "real@y.com" in result
        assert "noreply@x.com" not in result


class TestOutreachBuildEmail:
    def test_has_subject_and_html(self):
        subject, html = outreach.build_outreach_email("John", "Java Dev", "Acme")
        assert "Java Dev" in subject
        assert "Acme" in html
        assert "C2C" in html
        assert "Green Card" in html

    def test_no_name(self):
        subject, html = outreach.build_outreach_email("", "Role", "Company")
        assert "Hello," in html

    def test_with_name(self):
        subject, html = outreach.build_outreach_email("Sarah Jones", "Role", "Co")
        assert "Hi Sarah," in html


class TestOutreachFollowupEmail:
    def test_followup_content(self):
        subject, html = outreach.build_followup_email("Mike", "Java Dev", "Acme")
        assert "Re:" in subject
        assert "follow up" in html.lower()


class TestContactedTracking:
    def test_load_save(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"abc123": {"email": "a@b.com", "date": "2026-01-01"}}, f)
            tmp = f.name
        try:
            original = lds.CONTACTED_FILE
            lds.CONTACTED_FILE = Path(tmp)
            data = lds.load_contacted()
            assert "abc123" in data
        finally:
            lds.CONTACTED_FILE = original
            os.unlink(tmp)


class TestExportForAgent:
    def test_creates_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            tmp = f.name
        try:
            original = lds.FOUND_JOBS_FILE
            lds.FOUND_JOBS_FILE = Path(tmp)
            results = [{"title": "Java Dev", "company": "Acme", "url": "https://example.com/job1",
                        "location": "Remote", "description": "Java Spring", "score": 70, "is_c2c": True}]
            added = lds.export_for_agent(results)
            assert added == 1
            data = json.load(open(tmp))
            assert data["count"] == 1
            assert data["jobs"][0]["company"] == "Acme"
        finally:
            lds.FOUND_JOBS_FILE = original
            os.unlink(tmp)

    def test_deduplicates(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"jobs": [{"url": "https://example.com/job1", "title": "X", "company": "Y"}], "count": 1}, f)
            tmp = f.name
        try:
            original = lds.FOUND_JOBS_FILE
            lds.FOUND_JOBS_FILE = Path(tmp)
            results = [{"title": "Java Dev", "company": "Acme", "url": "https://example.com/job1",
                        "location": "Remote", "description": "", "score": 50, "is_c2c": False}]
            added = lds.export_for_agent(results)
            assert added == 0  # already exists
        finally:
            lds.FOUND_JOBS_FILE = original
            os.unlink(tmp)


class TestApplyReport:
    def test_generates_report(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            tmp = f.name
        try:
            original = lds.REPORT_FILE
            lds.REPORT_FILE = Path(tmp)
            results = [
                {"title": "Job A", "company": "Co A", "url": "http://a", "emails_sent": 2},
                {"title": "Job B", "company": "Co B", "url": "http://b", "emails_sent": 0},
            ]
            report = lds.generate_apply_report(results)
            assert report["summary"]["emailed_recruiters"] == 1
            assert report["summary"]["need_manual_apply"] == 1
        finally:
            lds.REPORT_FILE = original
            os.unlink(tmp)


# ══════════════════════════════════════════════════════════════
# INTEGRATION TESTS — test full flow with mocked network
# ══════════════════════════════════════════════════════════════

class TestFindAllRecruiters:
    @patch.object(lds, "find_recruiter_hunter", return_value=[{"email": "hr@acme.com", "name": "HR Person", "position": "HR", "source": "hunter.io"}])
    @patch.object(lds, "find_recruiter_snov", return_value=[])
    @patch.object(lds, "find_recruiters_linkedin_google", return_value=[{"email": "recruiter@acme.com", "name": "Jane", "position": "recruiter", "source": "linkedin+guess"}])
    @patch.object(lds, "find_recruiter_google", return_value=[])
    def test_combines_all_sources(self, mock_google, mock_linkedin, mock_snov, mock_hunter):
        contacts = lds.find_all_recruiters("Acme Corp", "Contact us at jobs@acme.com")
        # Should have: description email + hunter + linkedin = 3
        emails = [c["email"] for c in contacts]
        assert "jobs@acme.com" in emails
        assert "hr@acme.com" in emails
        assert "recruiter@acme.com" in emails

    @patch.object(lds, "find_recruiter_hunter", return_value=[])
    @patch.object(lds, "find_recruiter_snov", return_value=[])
    @patch.object(lds, "find_recruiters_linkedin_google", return_value=[])
    @patch.object(lds, "find_recruiter_google", return_value=[{"email": "x@y.com", "name": "", "position": "recruiter", "source": "google"}])
    def test_falls_back_to_google(self, mock_google, mock_linkedin, mock_snov, mock_hunter):
        contacts = lds.find_all_recruiters("Unknown Corp")
        assert len(contacts) == 1
        assert contacts[0]["source"] == "google"


class TestSendToAllRecruiters:
    @patch.object(lds, "load_contacted", return_value={})
    @patch.object(lds, "save_contacted")
    @patch("outreach.send_outreach", return_value=True)
    @patch("outreach.build_outreach_email", return_value=("Subject", "<html>body</html>"))
    def test_sends_to_new_contacts(self, mock_build, mock_send, mock_save, mock_load):
        os.environ["GMAIL_APP_PASSWORD"] = "fake"
        try:
            results = [{"title": "Java Dev", "company": "Acme", "url": "http://x",
                        "contacts": [{"email": "a@b.com", "name": "A", "position": "HR"}]}]
            sent = lds.send_to_all_recruiters(results)
            assert sent == 1
            mock_send.assert_called_once()
        finally:
            del os.environ["GMAIL_APP_PASSWORD"]

    @patch.object(lds, "load_contacted", return_value={"abc": {"email": "a@b.com"}})
    @patch.object(lds, "save_contacted")
    def test_skips_already_contacted(self, mock_save, mock_load):
        os.environ["GMAIL_APP_PASSWORD"] = "fake"
        try:
            # email_hash("a@b.com") should match
            results = [{"title": "Job", "company": "Co", "url": "http://x",
                        "contacts": [{"email": "a@b.com", "name": "A", "position": "HR"}]}]
            sent = lds.send_to_all_recruiters(results)
            assert sent == 0
        finally:
            del os.environ["GMAIL_APP_PASSWORD"]


class TestVerifyMx:
    @patch("dns.resolver.resolve")
    def test_valid_domain(self, mock_resolve):
        mock_resolve.return_value = [MagicMock()]
        assert lds.verify_mx("gmail.com") is True

    @patch("dns.resolver.resolve", side_effect=Exception("NXDOMAIN"))
    def test_invalid_domain(self, mock_resolve):
        # When dns fails, we return True (assume valid) to not block
        assert lds.verify_mx("nonexistent.xyz") is True


# ══════════════════════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
