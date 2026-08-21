"""Tests for Gemini CAPTCHA solver — unit tests without live API calls."""
import os
import re
from unittest.mock import patch, MagicMock

import pytest


# Ensure GEMINI_API_KEY is not required for import
@patch.dict(os.environ, {"GEMINI_API_KEY": ""})
def test_gemini_solver_no_key_returns_false():
    """Solver returns False when GEMINI_API_KEY is not set."""
    from src.gemini_captcha_solver import solve_captcha_with_gemini
    page = MagicMock()
    # Patch the module-level variable
    with patch("src.gemini_captcha_solver.GEMINI_API_KEY", ""):
        result = solve_captcha_with_gemini(page, "recaptcha")
    assert result is False


@patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-123"})
def test_gemini_solver_no_challenge_frame_returns_false():
    """Solver returns False when no challenge frame is found."""
    from src.gemini_captcha_solver import solve_captcha_with_gemini, _find_challenge_frame
    page = MagicMock()
    page.frames = []  # No frames at all
    with patch("src.gemini_captcha_solver.GEMINI_API_KEY", "test-key-123"):
        with patch("src.gemini_captcha_solver._find_challenge_frame", return_value=None):
            with patch("src.gemini_captcha_solver._click_captcha_checkbox", return_value=False):
                result = solve_captcha_with_gemini(page, "recaptcha")
    assert result is False


@patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-123"})
def test_gemini_ask_gemini_parses_response():
    """_ask_gemini correctly parses cell numbers from Gemini response."""
    from src.gemini_captcha_solver import _ask_gemini

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": "1,4,7"}]
            }
        }]
    }

    with patch("src.gemini_captcha_solver.GEMINI_API_KEY", "test-key-123"):
        with patch("requests.post", return_value=mock_response):
            cells = _ask_gemini(b"fake_image_bytes", "Select all traffic lights", "recaptcha")

    assert cells == [1, 4, 7]


@patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-123"})
def test_gemini_ask_gemini_handles_none_response():
    """_ask_gemini returns empty list when Gemini says NONE."""
    from src.gemini_captcha_solver import _ask_gemini

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": "NONE"}]
            }
        }]
    }

    with patch("src.gemini_captcha_solver.GEMINI_API_KEY", "test-key-123"):
        with patch("requests.post", return_value=mock_response):
            cells = _ask_gemini(b"fake_image_bytes", "Select all buses", "hcaptcha")

    assert cells == []


@patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-123"})
def test_gemini_ask_gemini_handles_api_error():
    """_ask_gemini returns empty list on API error."""
    from src.gemini_captcha_solver import _ask_gemini

    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.text = "Rate limited"

    with patch("src.gemini_captcha_solver.GEMINI_API_KEY", "test-key-123"):
        with patch("requests.post", return_value=mock_response):
            cells = _ask_gemini(b"fake_image_bytes", "Select all crosswalks", "recaptcha")

    assert cells == []


@patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-123"})
def test_gemini_ask_gemini_handles_network_error():
    """_ask_gemini returns empty list on network exception."""
    from src.gemini_captcha_solver import _ask_gemini
    import requests as _req

    with patch("src.gemini_captcha_solver.GEMINI_API_KEY", "test-key-123"):
        with patch("requests.post", side_effect=_req.exceptions.Timeout("timed out")):
            cells = _ask_gemini(b"fake_image_bytes", "Select all fire hydrants", "recaptcha")

    assert cells == []


@patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-123"})
def test_gemini_ask_gemini_deduplicates_cells():
    """_ask_gemini deduplicates repeated cell numbers."""
    from src.gemini_captcha_solver import _ask_gemini

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": "3, 3, 5, 5, 9"}]
            }
        }]
    }

    with patch("src.gemini_captcha_solver.GEMINI_API_KEY", "test-key-123"):
        with patch("requests.post", return_value=mock_response):
            cells = _ask_gemini(b"fake_image_bytes", "Select all bicycles", "hcaptcha")

    assert cells == [3, 5, 9]


@patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-123"})
def test_gemini_ask_gemini_filters_invalid_numbers():
    """_ask_gemini filters out numbers > 16 or < 1."""
    from src.gemini_captcha_solver import _ask_gemini

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": "0, 2, 17, 8, 99"}]
            }
        }]
    }

    with patch("src.gemini_captcha_solver.GEMINI_API_KEY", "test-key-123"):
        with patch("requests.post", return_value=mock_response):
            cells = _ask_gemini(b"fake_image_bytes", "Select all cars", "recaptcha")

    # Only 2 and 8 are valid (1-16 range)
    assert cells == [2, 8]


def test_gemini_solver_imports_correctly():
    """Verify the module can be imported without errors."""
    from src.gemini_captcha_solver import (
        solve_captcha_with_gemini,
        _find_challenge_frame,
        _click_captcha_checkbox,
        _screenshot_challenge,
        _get_challenge_instruction,
        _ask_gemini,
        _click_cells,
        _click_verify_button,
    )
    # All functions exist
    assert callable(solve_captcha_with_gemini)
    assert callable(_find_challenge_frame)
    assert callable(_ask_gemini)
    assert callable(_click_cells)
