"""Tests for visual analyzer — graceful fallback without API key."""
from src.visual_analyzer import analyze_screenshot, analyze_form_screenshot, PROFILE_CONTEXT


def test_profile_context():
    assert "Bob Rikh" in PROFILE_CONTEXT
    assert "bobrikh75@gmail.com" in PROFILE_CONTEXT


def test_analyze_without_key():
    """Without GEMINI_API_KEY, returns None gracefully."""
    import os
    os.environ.pop("GEMINI_API_KEY", None)
    result = analyze_screenshot(b"fake_image_data", "What do you see?")
    assert result is None


def test_form_analysis_without_key():
    import os
    os.environ.pop("GEMINI_API_KEY", None)
    result = analyze_form_screenshot(b"fake_image_data")
    assert result == []
