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


def test_profile_summary_is_built_from_profile_not_hardcoded():
    import re
    from src import ai_fallback
    src = open(ai_fallback.__file__).read()
    # no literal phone/email in source any more
    assert not re.search(r"\d{3}[ .-]\d{3}[ .-]\d{4}", src)
    assert not re.search(r"[\w.]+@[\w.]+\.(com|net)", src)
    out = ai_fallback.build_profile_summary({"name": "Test User", "email": "t@example.test", "phone": "555-000-0000"})
    assert "Test User" in out and "t@example.test" in out
    assert "<EMAIL>" in ai_fallback.build_profile_summary({})
