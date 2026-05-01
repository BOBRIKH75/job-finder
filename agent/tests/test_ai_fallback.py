"""Tests for AI fallback module."""
from src.ai_fallback import PROFILE_SUMMARY, ask_ai_about_field, ask_ai_cover_letter


def test_profile_summary_has_key_info():
    assert "Bob Rikh" in PROFILE_SUMMARY
    assert "bobrikh75@gmail.com" in PROFILE_SUMMARY
    assert "347-268-5917" in PROFILE_SUMMARY
    assert "Green Card" in PROFILE_SUMMARY
    assert "C2C" in PROFILE_SUMMARY


def test_ai_fallback_without_key():
    """Without GEMINI_API_KEY, should return None (graceful fallback)."""
    import os
    old = os.environ.get("GEMINI_API_KEY")
    os.environ.pop("GEMINI_API_KEY", None)
    result = ask_ai_about_field("What is your name?", "text")
    assert result is None
    if old:
        os.environ["GEMINI_API_KEY"] = old


def test_cover_letter_fallback_without_key():
    """Without API key, should return a default cover letter."""
    import os
    os.environ.pop("GEMINI_API_KEY", None)
    result = ask_ai_cover_letter("Java Dev", "Acme", "Java Spring Boot developer needed")
    assert "Java" in result
    assert len(result) > 50
