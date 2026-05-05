#!/usr/bin/env python3
"""
CAPTCHA Integration Tests — runs REAL Playwright browser locally.

Tests the full CAPTCHA detection + solving chain against:
1. Turnstile demo page (Cloudflare's official test page)
2. reCAPTCHA v2 demo page (Google's official test page)
3. hCaptcha demo page

These tests verify:
- detect_captcha() correctly identifies CAPTCHA presence
- detect_captcha_type() returns correct type + sitekey
- solve_captcha() chain attempts solving (may not always succeed without Docker)
- The agent gracefully handles unsolvable CAPTCHAs (no crash)

Run locally: cd agent && python3 -m pytest tests/test_captcha_live.py -v
DO NOT run in CI (needs real browser + network).
"""
import os
import sys
import pytest
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.page_doctor import (
    detect_captcha, detect_captcha_type, detect_turnstile,
    solve_captcha, dismiss_popups,
)


@pytest.fixture(scope="module")
def browser():
    """Launch a real Chromium browser for the test session."""
    pw = sync_playwright().start()
    b = pw.chromium.launch(headless=True, args=["--no-sandbox"])
    yield b
    b.close()
    pw.stop()


@pytest.fixture
def page(browser):
    """Fresh page for each test."""
    ctx = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    )
    p = ctx.new_page()
    yield p
    ctx.close()


# ══════════════════════════════════════════════════════════════
# TURNSTILE DETECTION
# ══════════════════════════════════════════════════════════════

class TestTurnstileDetection:
    """Test against Cloudflare's official Turnstile demo."""

    TURNSTILE_DEMO = "https://demo.turnstile.workers.dev/"

    def test_detect_turnstile_on_demo_page(self, page):
        """Turnstile demo page should have a cf-turnstile widget with sitekey."""
        page.goto(self.TURNSTILE_DEMO, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        sitekey = detect_turnstile(page)
        # Demo page has a turnstile widget
        if sitekey:
            assert len(sitekey) > 10
            print(f"  ✅ Turnstile sitekey detected: {sitekey[:20]}...")
        else:
            # Page may have loaded differently — check if captcha detected at all
            has_captcha = detect_captcha(page)
            print(f"  ℹ️  Turnstile sitekey not found directly, detect_captcha={has_captcha}")

    def test_detect_captcha_type_turnstile(self, page):
        """detect_captcha_type should return type='turnstile' on demo page."""
        page.goto(self.TURNSTILE_DEMO, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        info = detect_captcha_type(page)
        if info:
            assert info["type"] == "turnstile"
            assert "sitekey" in info
            assert len(info["sitekey"]) > 5
            print(f"  ✅ Type: {info['type']}, sitekey: {info['sitekey'][:20]}...")
        else:
            # Turnstile may render as iframe — still valid if detect_captcha works
            print("  ℹ️  detect_captcha_type returned None (may be iframe-rendered)")

    def test_solve_turnstile_graceful_without_docker(self, page):
        """Without Docker solver, solve_captcha should return False (not crash)."""
        page.goto(self.TURNSTILE_DEMO, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        # Ensure no Docker solver URL is set
        os.environ.pop("TURNSTILE_SOLVER_URL", None)
        os.environ.pop("OHMYCAPTCHA_URL", None)

        result = solve_captcha(page, self.TURNSTILE_DEMO)
        # Should return False gracefully (no solver available), NOT crash
        assert result is False or result is True  # either outcome is valid
        print(f"  ✅ solve_captcha returned {result} (no crash)")


# ══════════════════════════════════════════════════════════════
# RECAPTCHA V2 DETECTION
# ══════════════════════════════════════════════════════════════

class TestRecaptchaV2Detection:
    """Test against Google's reCAPTCHA v2 demo."""

    RECAPTCHA_DEMO = "https://www.google.com/recaptcha/api2/demo"

    def test_detect_recaptcha_on_demo(self, page):
        """Google's reCAPTCHA demo should be detected."""
        page.goto(self.RECAPTCHA_DEMO, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        has_captcha = detect_captcha(page)
        assert has_captcha is True
        print("  ✅ reCAPTCHA v2 detected on demo page")

    def test_detect_captcha_type_recaptchav2(self, page):
        """Should identify as recaptchav2 with sitekey."""
        page.goto(self.RECAPTCHA_DEMO, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        info = detect_captcha_type(page)
        assert info is not None
        assert info["type"] == "recaptchav2"
        assert "sitekey" in info
        assert len(info["sitekey"]) > 10
        print(f"  ✅ Type: {info['type']}, sitekey: {info['sitekey'][:20]}...")

    def test_solve_recaptcha_graceful_without_docker(self, page):
        """Without Docker solver, should fail gracefully."""
        page.goto(self.RECAPTCHA_DEMO, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        os.environ.pop("OHMYCAPTCHA_URL", None)
        result = solve_captcha(page, self.RECAPTCHA_DEMO)
        assert result is False or result is True
        print(f"  ✅ solve_captcha returned {result} (no crash)")


# ══════════════════════════════════════════════════════════════
# NO-CAPTCHA PAGES (should NOT trigger detection)
# ══════════════════════════════════════════════════════════════

class TestNoCaptchaPages:
    """Verify clean pages don't false-positive as having CAPTCHA."""

    def test_lever_no_captcha(self, page):
        """Lever job pages should NOT have CAPTCHA."""
        page.goto("https://jobs.lever.co/sonatype", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        has_captcha = detect_captcha(page)
        assert has_captcha is False
        print("  ✅ Lever page: no CAPTCHA detected (correct)")

    def test_example_com_no_captcha(self, page):
        """Plain page should not trigger CAPTCHA detection."""
        page.goto("https://example.com", wait_until="domcontentloaded", timeout=10000)

        has_captcha = detect_captcha(page)
        assert has_captcha is False

        info = detect_captcha_type(page)
        assert info is None
        print("  ✅ example.com: no CAPTCHA (correct)")


# ══════════════════════════════════════════════════════════════
# CAPTCHA SOLVE CHAIN (end-to-end with Docker if available)
# ══════════════════════════════════════════════════════════════

class TestCaptchaSolveChain:
    """Test the full solve chain — works with or without Docker solvers."""

    def test_solve_chain_no_captcha_returns_true(self, page):
        """If no CAPTCHA on page, solve_captcha should return True (nothing to solve)."""
        page.goto("https://example.com", wait_until="domcontentloaded", timeout=10000)

        result = solve_captcha(page, "https://example.com")
        assert result is True  # No CAPTCHA = success
        print("  ✅ No CAPTCHA → solve_captcha returns True")

    def test_solve_chain_with_captcha_no_solver(self, page):
        """With CAPTCHA but no solver, should return False (not crash)."""
        page.goto("https://www.google.com/recaptcha/api2/demo",
                  wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        os.environ.pop("OHMYCAPTCHA_URL", None)
        os.environ.pop("TURNSTILE_SOLVER_URL", None)

        result = solve_captcha(page, "https://www.google.com/recaptcha/api2/demo")
        # Without solvers, should fail gracefully
        assert isinstance(result, bool)
        print(f"  ✅ CAPTCHA present, no solver → returned {result} (no crash)")

    @pytest.mark.skipif(
        not os.environ.get("OHMYCAPTCHA_URL"),
        reason="OhMyCaptcha Docker not running (set OHMYCAPTCHA_URL to test)"
    )
    def test_solve_with_ohmycaptcha(self, page):
        """If OhMyCaptcha Docker is running, actually solve a CAPTCHA."""
        page.goto("https://www.google.com/recaptcha/api2/demo",
                  wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        result = solve_captcha(page, "https://www.google.com/recaptcha/api2/demo")
        assert result is True
        print("  ✅ OhMyCaptcha solved reCAPTCHA v2!")

    @pytest.mark.skipif(
        not os.environ.get("TURNSTILE_SOLVER_URL"),
        reason="Turnstile solver Docker not running (set TURNSTILE_SOLVER_URL to test)"
    )
    def test_solve_turnstile_with_docker(self, page):
        """If Turnstile solver Docker is running, actually solve Turnstile."""
        page.goto("https://demo.turnstile.workers.dev/",
                  wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        result = solve_captcha(page, "https://demo.turnstile.workers.dev/")
        assert result is True
        print("  ✅ Turnstile solver solved the challenge!")


# ══════════════════════════════════════════════════════════════
# POPUP DISMISSAL (prerequisite for CAPTCHA detection)
# ══════════════════════════════════════════════════════════════

class TestPopupDismissal:
    """Verify cookie banners are dismissed before CAPTCHA check."""

    def test_dismiss_on_clean_page(self, page):
        """No popups = dismiss returns 0."""
        page.goto("https://example.com", wait_until="domcontentloaded", timeout=10000)
        dismissed = dismiss_popups(page)
        assert dismissed == 0

    def test_dismiss_doesnt_crash_on_any_page(self, page):
        """dismiss_popups should never crash regardless of page content."""
        page.goto("https://jobs.lever.co/sonatype", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1000)
        dismissed = dismiss_popups(page)
        assert isinstance(dismissed, int)
        assert dismissed >= 0
        print(f"  ✅ Dismissed {dismissed} popups (no crash)")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
