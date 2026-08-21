#!/usr/bin/env python3
"""
Gemini Flash CAPTCHA Solver — FREE visual CAPTCHA solving via Google Gemini multimodal API.

How it works:
1. Takes a screenshot of the CAPTCHA challenge (image grid)
2. Sends to Gemini 2.5 Flash with a vision prompt asking what to click
3. Parses Gemini's response to identify which grid cells to click
4. Clicks the identified cells using Playwright

Supports:
- reCAPTCHA v2 image grids ("Select all images with traffic lights")
- hCaptcha image selection ("Select all images containing a bicycle")

Cost: FREE — Gemini Flash offers 1000+ free requests/day via API key.
Requires: GEMINI_API_KEY environment variable (already configured as GitHub secret).

This is a FALLBACK — only used when CapSolver has no balance (ERROR_KEY_DENIED_ACCESS).
"""

import os
import re
import time
import base64
import logging
from typing import Optional

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash-preview-05-20"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

# Max attempts to solve a single CAPTCHA (new images may appear after first selection)
MAX_SOLVE_ATTEMPTS = 3


def solve_captcha_with_gemini(page, captcha_type: str = "recaptcha") -> bool:
    """Solve a visual CAPTCHA using Gemini Flash vision.

    Args:
        page: Playwright page object (sync API)
        captcha_type: "recaptcha" or "hcaptcha"

    Returns:
        True if solved successfully, False otherwise
    """
    if not GEMINI_API_KEY:
        logger.info("      ⚠️ Gemini CAPTCHA: GEMINI_API_KEY not set")
        return False

    print(f"      🤖 Gemini CAPTCHA solver: attempting {captcha_type} solve...")

    try:
        for attempt in range(MAX_SOLVE_ATTEMPTS):
            # Step 1: Find the CAPTCHA challenge frame/element
            challenge_frame = _find_challenge_frame(page, captcha_type)
            if not challenge_frame:
                # Maybe the CAPTCHA checkbox needs clicking first
                if attempt == 0:
                    if _click_captcha_checkbox(page, captcha_type):
                        time.sleep(2)
                        challenge_frame = _find_challenge_frame(page, captcha_type)
                if not challenge_frame:
                    print(f"      ⚠️ Gemini CAPTCHA: no challenge frame found (attempt {attempt + 1})")
                    if attempt == 0:
                        return False
                    # After first attempt, challenge may have disappeared = solved
                    break

            # Step 2: Take screenshot of the challenge
            screenshot_bytes = _screenshot_challenge(challenge_frame, captcha_type)
            if not screenshot_bytes:
                print(f"      ⚠️ Gemini CAPTCHA: screenshot failed")
                return False

            # Step 3: Get the challenge instruction text
            instruction = _get_challenge_instruction(challenge_frame, captcha_type)
            if not instruction:
                instruction = "Select all matching images"

            print(f"      📸 Challenge: '{instruction}' (attempt {attempt + 1}/{MAX_SOLVE_ATTEMPTS})")

            # Step 4: Send to Gemini for analysis
            cells_to_click = _ask_gemini(screenshot_bytes, instruction, captcha_type)
            if not cells_to_click:
                print(f"      ⚠️ Gemini returned no cells to click")
                return False

            print(f"      🎯 Gemini says click cells: {cells_to_click}")

            # Step 5: Click the identified cells
            _click_cells(challenge_frame, cells_to_click, captcha_type)
            time.sleep(1.5)

            # Step 6: Click verify/submit button
            _click_verify_button(challenge_frame, captcha_type)
            time.sleep(3)

            # Step 7: Check if solved (challenge frame disappeared or new images appeared)
            new_frame = _find_challenge_frame(page, captcha_type)
            if not new_frame:
                print(f"      ✅ Gemini CAPTCHA solved on attempt {attempt + 1}!")
                return True
            # New images appeared — loop and try again

        # Check final state — maybe it was solved on last attempt
        time.sleep(2)
        if not _find_challenge_frame(page, captcha_type):
            print(f"      ✅ Gemini CAPTCHA solved!")
            return True

        print(f"      ❌ Gemini CAPTCHA: max attempts reached")
        return False

    except Exception as e:
        print(f"      ❌ Gemini CAPTCHA error: {str(e)[:100]}")
        return False


def _find_challenge_frame(page, captcha_type: str):
    """Find the CAPTCHA challenge iframe/element.

    Returns the frame object (for reCAPTCHA) or element handle (for hCaptcha).
    """
    try:
        if captcha_type == "recaptcha":
            # reCAPTCHA v2 challenge opens in a separate iframe
            for frame in page.frames:
                if "recaptcha" in frame.url and "bframe" in frame.url:
                    # Check if the challenge table is visible
                    try:
                        table = frame.locator("table.rc-imageselect-table, .rc-imageselect-challenge")
                        if table.count() > 0 and table.first.is_visible(timeout=1000):
                            return frame
                    except Exception:
                        pass
            # Also check for the rc-imageselect div directly
            for frame in page.frames:
                if "recaptcha" in frame.url:
                    try:
                        challenge = frame.locator(".rc-imageselect")
                        if challenge.count() > 0 and challenge.first.is_visible(timeout=1000):
                            return frame
                    except Exception:
                        pass

        elif captcha_type == "hcaptcha":
            # hCaptcha challenge opens in an iframe with newassets.hcaptcha.com
            for frame in page.frames:
                if "hcaptcha" in frame.url and ("challenge" in frame.url or "newassets" in frame.url):
                    try:
                        # Check if task grid is visible
                        grid = frame.locator(".task-image, .challenge-container, .task-grid")
                        if grid.count() > 0 and grid.first.is_visible(timeout=1000):
                            return frame
                    except Exception:
                        pass

    except Exception as e:
        logger.debug(f"Challenge frame search error: {str(e)[:60]}")

    return None


def _click_captcha_checkbox(page, captcha_type: str) -> bool:
    """Click the initial CAPTCHA checkbox to trigger the image challenge."""
    try:
        if captcha_type == "recaptcha":
            # Find the reCAPTCHA anchor iframe and click the checkbox
            for frame in page.frames:
                if "recaptcha" in frame.url and "anchor" in frame.url:
                    checkbox = frame.locator("#recaptcha-anchor, .recaptcha-checkbox")
                    if checkbox.count() > 0:
                        checkbox.first.click()
                        return True
        elif captcha_type == "hcaptcha":
            # Find hCaptcha checkbox iframe
            for frame in page.frames:
                if "hcaptcha" in frame.url and "checkbox" in frame.url:
                    checkbox = frame.locator("#checkbox, .check")
                    if checkbox.count() > 0:
                        checkbox.first.click()
                        return True
    except Exception:
        pass
    return False


def _screenshot_challenge(frame, captcha_type: str) -> Optional[bytes]:
    """Take a screenshot of the CAPTCHA challenge area."""
    try:
        if captcha_type == "recaptcha":
            # Screenshot the entire image select area
            challenge = frame.locator(".rc-imageselect, .rc-imageselect-challenge")
            if challenge.count() > 0 and challenge.first.is_visible(timeout=2000):
                return challenge.first.screenshot()
        elif captcha_type == "hcaptcha":
            # Screenshot the task/challenge area
            for sel in [".challenge-container", ".task-grid", ".challenge-view"]:
                challenge = frame.locator(sel)
                if challenge.count() > 0 and challenge.first.is_visible(timeout=2000):
                    return challenge.first.screenshot()

        # Fallback: screenshot the entire frame content
        # Use frame.locator("body") for frame-level screenshot
        body = frame.locator("body")
        if body.count() > 0:
            return body.first.screenshot()

    except Exception as e:
        logger.debug(f"Screenshot error: {str(e)[:60]}")

    return None


def _get_challenge_instruction(frame, captcha_type: str) -> str:
    """Extract the challenge instruction text (e.g., 'Select all images with traffic lights')."""
    try:
        if captcha_type == "recaptcha":
            # Instruction is in rc-imageselect-desc or rc-imageselect-instructions
            for sel in [".rc-imageselect-desc-wrapper", ".rc-imageselect-desc",
                        ".rc-imageselect-instructions"]:
                el = frame.locator(sel)
                if el.count() > 0:
                    text = el.first.inner_text(timeout=1000).strip()
                    if text:
                        return text
        elif captcha_type == "hcaptcha":
            # Instruction is in .prompt-text or .challenge-header
            for sel in [".prompt-text", ".challenge-header h2", ".task-title",
                        "[class*='prompt']"]:
                el = frame.locator(sel)
                if el.count() > 0:
                    text = el.first.inner_text(timeout=1000).strip()
                    if text:
                        return text
    except Exception:
        pass
    return ""


def _ask_gemini(screenshot_bytes: bytes, instruction: str, captcha_type: str) -> list[int]:
    """Send screenshot to Gemini Flash and get which cells to click.

    Returns a list of 1-indexed cell numbers (e.g., [1, 4, 7] for a 3x3 grid).
    """
    import requests as _req

    # Encode screenshot as base64
    img_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

    # Build the prompt based on CAPTCHA type
    if captcha_type == "recaptcha":
        prompt = f"""You are looking at a reCAPTCHA image challenge. 
The instruction says: "{instruction}"

The image shows a grid of smaller images (typically 3x3 = 9 cells or 4x4 = 16 cells).
The cells are numbered left-to-right, top-to-bottom starting at 1.
For a 3x3 grid: top row is 1,2,3 — middle row is 4,5,6 — bottom row is 7,8,9.
For a 4x4 grid: top row is 1,2,3,4 — second row is 5,6,7,8 — etc.

Look carefully at each cell image and determine which ones match the instruction.
Respond with ONLY a comma-separated list of cell numbers that match.
Example: 1,4,7
If no cells match, respond with: NONE

Which cells match the instruction?"""
    else:  # hcaptcha
        prompt = f"""You are looking at an hCaptcha image challenge.
The instruction says: "{instruction}"

The image shows a grid of smaller images (typically 3x3 = 9 cells).
The cells are numbered left-to-right, top-to-bottom starting at 1.
Top row is 1,2,3 — middle row is 4,5,6 — bottom row is 7,8,9.

Look carefully at each cell image and determine which ones match the instruction.
Respond with ONLY a comma-separated list of cell numbers that match.
Example: 2,5,8
If no cells match, respond with: NONE

Which cells match the instruction?"""

    # Call Gemini API
    url = GEMINI_API_URL.format(model=GEMINI_MODEL, key=GEMINI_API_KEY)
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": img_b64
                    }
                }
            ]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 50,
        }
    }

    try:
        resp = _req.post(url, json=payload, timeout=30)
        if resp.status_code != 200:
            print(f"      ⚠️ Gemini API error: HTTP {resp.status_code} — {resp.text[:100]}")
            return []

        data = resp.json()
        # Extract text from response
        text = ""
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            for part in parts:
                if "text" in part:
                    text += part["text"]

        text = text.strip()
        print(f"      📝 Gemini response: '{text}'")

        if "NONE" in text.upper():
            return []

        # Parse comma-separated numbers from response
        numbers = re.findall(r'\d+', text)
        cells = [int(n) for n in numbers if 1 <= int(n) <= 16]

        # Deduplicate while preserving order
        seen = set()
        unique_cells = []
        for c in cells:
            if c not in seen:
                seen.add(c)
                unique_cells.append(c)

        return unique_cells

    except Exception as e:
        print(f"      ⚠️ Gemini API call failed: {str(e)[:80]}")
        return []


def _click_cells(frame, cells: list[int], captcha_type: str) -> None:
    """Click the specified cells in the CAPTCHA grid.

    Args:
        frame: The challenge frame (Playwright Frame object)
        cells: List of 1-indexed cell numbers to click
        captcha_type: "recaptcha" or "hcaptcha"
    """
    import random

    try:
        if captcha_type == "recaptcha":
            # reCAPTCHA uses table cells: td.rc-imageselect-tile or individual images
            # Cells are ordered left-to-right, top-to-bottom
            tile_selectors = [
                "td.rc-imageselect-tile",  # Standard 3x3
                ".rc-imageselect-tile",    # Alternative
                "table.rc-imageselect-table td",  # Table cells
            ]
            for sel in tile_selectors:
                tiles = frame.locator(sel).all()
                if tiles:
                    for cell_num in cells:
                        idx = cell_num - 1  # Convert to 0-indexed
                        if 0 <= idx < len(tiles):
                            try:
                                tiles[idx].click()
                                time.sleep(random.uniform(0.3, 0.7))
                            except Exception:
                                pass
                    return

            # Fallback: try clicking by image index
            images = frame.locator(".rc-image-tile-wrapper, .rc-imageselect-tile img").all()
            if images:
                for cell_num in cells:
                    idx = cell_num - 1
                    if 0 <= idx < len(images):
                        try:
                            images[idx].click()
                            time.sleep(random.uniform(0.3, 0.7))
                        except Exception:
                            pass

        elif captcha_type == "hcaptcha":
            # hCaptcha uses .task-image divs or .image cells
            tile_selectors = [
                ".task-image",
                ".image-wrapper",
                ".cell",
                "[class*='task'] [class*='image']",
            ]
            for sel in tile_selectors:
                tiles = frame.locator(sel).all()
                if tiles:
                    for cell_num in cells:
                        idx = cell_num - 1
                        if 0 <= idx < len(tiles):
                            try:
                                tiles[idx].click()
                                time.sleep(random.uniform(0.3, 0.7))
                            except Exception:
                                pass
                    return

    except Exception as e:
        logger.debug(f"Click cells error: {str(e)[:60]}")


def _click_verify_button(frame, captcha_type: str) -> None:
    """Click the verify/check/submit button in the challenge frame."""
    try:
        if captcha_type == "recaptcha":
            # reCAPTCHA verify button
            for sel in ["#recaptcha-verify-button", ".rc-button-default",
                        "button:has-text('Verify')", "button:has-text('VERIFY')"]:
                btn = frame.locator(sel)
                if btn.count() > 0 and btn.first.is_visible(timeout=1000):
                    btn.first.click()
                    return

        elif captcha_type == "hcaptcha":
            # hCaptcha verify button
            for sel in [".button-submit", ".verify-button",
                        "button:has-text('Verify')", "button:has-text('Check')"]:
                btn = frame.locator(sel)
                if btn.count() > 0 and btn.first.is_visible(timeout=1000):
                    btn.first.click()
                    return

    except Exception:
        pass
