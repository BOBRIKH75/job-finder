"""Tests for email_code_reader — verification code extraction logic."""
from unittest.mock import patch, MagicMock
from src.email_code_reader import _extract_code, get_verification_code, handle_email_verification


class TestExtractCode:
    """Test code extraction from various email body formats."""

    def test_explicit_verification_code_text(self):
        body = "Your verification code is: 482916"
        assert _extract_code(body) == "482916"

    def test_security_code_with_colon(self):
        body = "Security code: 739201"
        assert _extract_code(body) == "739201"

    def test_confirmation_code_no_colon(self):
        body = "Your confirmation code is 123456"
        assert _extract_code(body) == "123456"

    def test_code_in_strong_tag(self):
        body = "<p>Enter this code: <strong>847291</strong></p>"
        assert _extract_code(body) == "847291"

    def test_code_in_bold_tag(self):
        body = "<p>Your code: <b>593017</b></p>"
        assert _extract_code(body) == "593017"

    def test_standalone_6_digit_code(self):
        body = "Here is your code to verify your identity.\n\n291847\n\nDo not share this."
        assert _extract_code(body) == "291847"

    def test_4_digit_code(self):
        body = "Your PIN is: 4829"
        assert _extract_code(body) == "4829"

    def test_8_digit_code(self):
        body = "Verification code: 48291637"
        assert _extract_code(body) == "48291637"

    def test_no_code_found(self):
        body = "Welcome to our platform! Click the link below to get started."
        assert _extract_code(body) is None

    def test_alphanumeric_code(self):
        body = "Use this code to verify: AB7C2D9E"
        # The alphanumeric pattern should match
        result = _extract_code(body)
        assert result is not None

    def test_greenhouse_style_email(self):
        """Greenhouse typically sends 'Your security code is XXXXXX'."""
        body = """
        <html><body>
        <p>Hi,</p>
        <p>Your security code is <strong>847291</strong></p>
        <p>Enter this code to verify your identity.</p>
        </body></html>
        """
        assert _extract_code(body) == "847291"

    def test_code_with_dash_separator(self):
        body = "Verification code - 192847"
        assert _extract_code(body) == "192847"

    # ── Regression tests for the 2026-09-01 OTP-rejection fix ──────────────
    # Real codes seen in production Greenhouse emails (from cicd_error_history).
    def test_alphanumeric_not_truncated(self):
        """15372C must NOT be truncated to 15372 (caused verification_code_rejected)."""
        assert _extract_code("security code: 15372C please enter") == "15372C"

    def test_greenhouse_8char_alpha_token(self):
        assert _extract_code("Copy and paste this code: EEtMwNKJ to resubmit") == "EEtMwNKJ"

    def test_greenhouse_8char_alnum_token(self):
        assert _extract_code("Your code: 4SSHR6aH — enter to verify") == "4SSHR6aH"

    def test_greenhouse_8char_hex_lower(self):
        assert _extract_code("code cb164f12 confirm your email") == "cb164f12"

    def test_css_colour_not_matched_as_code(self):
        """A CSS colour like #15372C must be ignored; the real code wins."""
        body = "color #15372C font enter your security code 7391Q2 now"
        assert _extract_code(body) == "7391Q2"

    def test_capitalized_words_not_matched(self):
        """Sentence words like 'Security'/'Colorado' must not be picked as the code."""
        body = "Security Please Colorado enter code below XWHfrfdC thanks"
        assert _extract_code(body) == "XWHfrfdC"

    # ── Regression for the 2026-09-01 live-run false positive ──────────────
    # A real run matched the word "LinkedIn" (8-char CamelCase) as a code.
    def test_camelcase_words_not_matched_as_code(self):
        for word in ("LinkedIn", "YourName", "JobAlert", "TeamName"):
            assert _extract_code(word) is None, f"{word} wrongly matched as code"

    def test_linkedin_in_body_picks_real_code(self):
        """'LinkedIn' in the signature must not beat the real code in the body."""
        body = ("Connect with us on LinkedIn. Your security code is bd316sx4. "
                "Paste it to resubmit your application.")
        assert _extract_code(body) == "bd316sx4"

    def test_real_greenhouse_alpha_codes_still_work(self):
        """Random >=3-uppercase Greenhouse tokens must still extract."""
        assert _extract_code("code EEtMwNKJ") == "EEtMwNKJ"
        assert _extract_code("code XWHfrfdC") == "XWHfrfdC"


class TestGetVerificationCode:
    """Test IMAP polling behavior (mocked)."""

    @patch.dict("os.environ", {"GMAIL_USER": "", "GMAIL_APP_PASSWORD": ""})
    def test_returns_none_when_no_credentials(self):
        result = get_verification_code(max_wait_seconds=1, poll_interval=1)
        assert result is None

    @patch("src.email_code_reader.imaplib.IMAP4_SSL")
    @patch.dict("os.environ", {"GMAIL_USER": "test@gmail.com", "GMAIL_APP_PASSWORD": "pass123"})
    def test_returns_code_from_email(self, mock_imap_cls):
        """Simulate finding a verification email with code."""
        mock_mail = MagicMock()
        mock_imap_cls.return_value = mock_mail
        mock_mail.login.return_value = ("OK", [])
        mock_mail.select.return_value = ("OK", [b"1"])
        mock_mail.search.return_value = ("OK", [b"1"])
        
        # Build a fake email with verification code
        import email as email_mod
        from email.mime.text import MIMEText
        msg = MIMEText("Your verification code is: 482916")
        msg["From"] = "noreply@greenhouse.io"
        msg["Subject"] = "Verification Code"
        raw = msg.as_bytes()
        
        mock_mail.fetch.return_value = ("OK", [(b"1", raw)])
        mock_mail.store.return_value = ("OK", [])
        mock_mail.logout.return_value = ("OK", [])
        
        result = get_verification_code(sender_filter="greenhouse", max_wait_seconds=5, poll_interval=1)
        assert result == "482916"

    @patch("src.email_code_reader.imaplib.IMAP4_SSL")
    @patch.dict("os.environ", {"GMAIL_USER": "test@gmail.com", "GMAIL_APP_PASSWORD": "pass123"})
    def test_returns_none_when_no_emails(self, mock_imap_cls):
        """No matching emails found within timeout."""
        mock_mail = MagicMock()
        mock_imap_cls.return_value = mock_mail
        mock_mail.login.return_value = ("OK", [])
        mock_mail.select.return_value = ("OK", [b"1"])
        mock_mail.search.return_value = ("OK", [b""])  # No messages
        mock_mail.logout.return_value = ("OK", [])
        
        result = get_verification_code(sender_filter="greenhouse", max_wait_seconds=4, poll_interval=2)
        assert result is None


class TestHandleEmailVerification:
    """Test the full handle flow (page detection + code entry)."""

    def test_returns_false_when_no_verification_signals(self):
        """Page doesn't mention verification — should return False immediately."""
        mock_page = MagicMock()
        mock_body = MagicMock()
        mock_page.locator.return_value = mock_body
        mock_body.inner_text.return_value = "Thank you for applying! We'll review your application."
        
        result = handle_email_verification(mock_page)
        assert result is False

    @patch("src.email_code_reader.get_verification_code")
    def test_detects_verification_and_enters_code(self, mock_get_code):
        """Page shows verification prompt + code is found."""
        mock_get_code.return_value = "482916"
        
        mock_page = MagicMock()
        # First locator call for body text detection
        mock_body = MagicMock()
        mock_body.inner_text.return_value = "We sent a code to your email. Enter the verification code below."
        
        # For enter_verification_code: locator for input field
        mock_field = MagicMock()
        mock_field.is_visible.return_value = True
        mock_field.fill.return_value = None
        
        # For button click
        mock_btn = MagicMock()
        mock_btn.is_visible.return_value = True
        mock_btn.click.return_value = None
        
        # Mock locator chain: body → input → button
        call_count = [0]
        def mock_locator(sel):
            call_count[0] += 1
            if sel == "body":
                return mock_body
            mock_loc = MagicMock()
            mock_loc.first = mock_field if "input" in sel or sel.startswith("#") else mock_btn
            return mock_loc
        
        mock_page.locator = mock_locator
        mock_page.wait_for_timeout = MagicMock()
        
        result = handle_email_verification(mock_page)
        assert result is True

    @patch("src.email_code_reader.get_verification_code")
    def test_returns_false_when_no_code_found(self, mock_get_code):
        """Page shows verification but no email arrives."""
        mock_get_code.return_value = None
        
        mock_page = MagicMock()
        mock_body = MagicMock()
        mock_body.inner_text.return_value = "Check your email for a verification code"
        mock_page.locator.return_value = mock_body
        
        result = handle_email_verification(mock_page)
        assert result is False
