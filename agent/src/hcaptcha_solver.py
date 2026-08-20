#!/usr/bin/env python3
"""
hCaptcha Solver using Gemini Vision AI — FREE, no paid API.

Solves hCaptcha image grid challenges by:
1. Detecting the hCaptcha iframe and challenge
2. Reading the instruction (e.g., "Select all images with a bus")
3. Screenshotting the full grid as ONE image
4. Sending to Gemini Vision: "Which squares (1-9) contain {object}?"
5. Clicking the identified tiles
6. Submitting the challenge

Uses Gemini 2.0 Flash (free tier, fast, good at image recognition).
Requires: GEMINI_API_KEY environment variable.

This is an OPTIONAL solver — added on top of existing chain.
If it fails, the existing fallback flow (email outreach) handles it.
"""

import os
import re
import time
import base64
from pathlib import Path
from typing import Optional


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"


def solve_hcaptcha(page, max_attempts: int = 3) -> bool:
    """Main entry point: detect and solve hCaptcha on the current page.
    
    Args:
        page: Playwright page object
        max_attempts: How many times to retry the challenge
        
    Returns:
        True if hCaptcha was solved, False otherwise
    """
    if not GEMINI_API_KEY:
        print("      ⚠️ hCaptcha solver: GEMINI_API_KEY not set — skipping")
        return False
    
    # Step 1: Find the hCaptcha challenge iframe
    hcaptcha_frame = _find_hcaptcha_challenge_frame(page)
    if not hcaptcha_frame:
        # Maybe we need to click the hCaptcha checkbox first
        if not _click_hcaptcha_checkbox(page):
            print("      ⚠️ hCaptcha: no challenge found")
            return False
        time.sleep(3)
        hcaptcha_frame = _find_hcaptcha_challenge_frame(page)
        if not hcaptcha_frame:
            # Check if clicking checkbox was enough (no challenge appeared)
            if _is_hcaptcha_solved(page):
                print("      ✅ hCaptcha solved (checkbox only)")
                return True
            print("      ⚠️ hCaptcha: challenge didn't appear after checkbox click")
            return False
    
    for attempt in range(max_attempts):
        print(f"      🧩 hCaptcha attempt {attempt + 1}/{max_attempts}")
        
        # Step 2: Read the challenge instruction
        instruction = _read_instruction(hcaptcha_frame)
        if not instruction:
            print("      ⚠️ hCaptcha: couldn't read instruction")
            return False
        
        target_object = _extract_target_object(instruction)
        print(f"      📋 Challenge: '{instruction}' → target: '{target_object}'")
        
        # Step 3: Screenshot the image grid
        grid_screenshot = _screenshot_grid(hcaptcha_frame)
        if not grid_screenshot:
            print("      ⚠️ hCaptcha: couldn't screenshot grid")
            return False
        
        # Step 4: Ask Gemini which tiles contain the target object
        tiles_to_click = _ask_gemini_which_tiles(grid_screenshot, target_object, instruction)
        if not tiles_to_click:
            print("      ⚠️ hCaptcha: Gemini returned no tiles")
            # Try clicking "skip" if available
            if _click_skip(hcaptcha_frame):
                time.sleep(2)
                if _is_hcaptcha_solved(page):
                    return True
                continue
            return False
        
        print(f"      🎯 Clicking tiles: {tiles_to_click}")
        
        # Step 5: Click the identified tiles
        _click_tiles(hcaptcha_frame, tiles_to_click)
        time.sleep(1)
        
        # Step 6: Submit/verify
        _click_verify(hcaptcha_frame)
        time.sleep(3)
        
        # Check if solved
        if _is_hcaptcha_solved(page):
            print(f"      ✅ hCaptcha SOLVED (attempt {attempt + 1})")
            return True
        
        # Check if a new challenge appeared (need to solve again)
        hcaptcha_frame = _find_hcaptcha_challenge_frame(page)
        if not hcaptcha_frame:
            # No challenge frame = might be solved or might have failed
            time.sleep(2)
            if _is_hcaptcha_solved(page):
                print(f"      ✅ hCaptcha SOLVED (attempt {attempt + 1})")
                return True
            print("      ⚠️ hCaptcha: challenge disappeared but not solved")
            return False
    
    print(f"      ❌ hCaptcha: failed after {max_attempts} attempts")
    return False


def _find_hcaptcha_challenge_frame(page):
    """Find the hCaptcha challenge iframe (the grid with images)."""
    try:
        # hCaptcha challenge appears in an iframe with src containing hcaptcha.com
        for frame in page.frames:
            if "hcaptcha.com" in (frame.url or "") and "challenge" in (frame.url or ""):
                return frame
        # Also try by name pattern
        for frame in page.frames:
            url = frame.url or ""
            if "newassets.hcaptcha.com" in url or "imgs.hcaptcha.com" in url:
                return frame
    except Exception:
        pass
    return None


def _click_hcaptcha_checkbox(page) -> bool:
    """Click the hCaptcha checkbox to trigger the challenge."""
    try:
        # The checkbox is in a separate iframe
        for frame in page.frames:
            if "hcaptcha.com" in (frame.url or "") and "challenge" not in (frame.url or ""):
                try:
                    checkbox = frame.locator('#checkbox, .check')
                    if checkbox.count() > 0:
                        checkbox.first.click()
                        time.sleep(2)
                        return True
                except Exception:
                    pass
        
        # Fallback: click on the hCaptcha container div
        hc_div = page.locator('.h-captcha iframe, [data-hcaptcha-widget-id]')
        if hc_div.count() > 0:
            hc_div.first.click()
            time.sleep(2)
            return True
    except Exception:
        pass
    return False


def _is_hcaptcha_solved(page) -> bool:
    """Check if hCaptcha has been solved (response token exists)."""
    try:
        result = page.evaluate("""() => {
            const ta = document.querySelector('[name="h-captcha-response"], textarea[name*="hcaptcha"]');
            if (ta && ta.value && ta.value.length > 20) return true;
            const iframes = document.querySelectorAll('iframe[data-hcaptcha-response]');
            for (const f of iframes) {
                if (f.getAttribute('data-hcaptcha-response') && f.getAttribute('data-hcaptcha-response').length > 20) return true;
            }
            return false;
        }""")
        return result
    except Exception:
        return False


def _read_instruction(frame) -> str:
    """Read the challenge instruction text from the hCaptcha frame."""
    try:
        # hCaptcha puts the instruction in .prompt-text or similar
        selectors = [
            '.prompt-text',
            '.challenge-header .prompt-text',
            'h2.prompt-text',
            '.task-grid .prompt-text',
            '[class*="prompt"]',
        ]
        for sel in selectors:
            try:
                el = frame.locator(sel)
                if el.count() > 0:
                    text = el.first.inner_text()
                    if text and len(text) > 3:
                        return text.strip()
            except Exception:
                continue
        
        # Fallback: get any header text in the challenge
        try:
            body_text = frame.locator('body').inner_text()[:500]
            # Look for "Please click each image containing" or "Select all images with"
            match = re.search(r'(?:click|select|choose).*?(?:containing|with|showing)\s+(?:a\s+)?(.+?)(?:\.|$)', body_text, re.IGNORECASE)
            if match:
                return match.group(0).strip()
        except Exception:
            pass
    except Exception:
        pass
    return ""


def _extract_target_object(instruction: str) -> str:
    """Extract the target object name from the instruction text.
    
    E.g., "Please click each image containing a motorbus" → "motorbus"
    E.g., "Select all images with a bicycle" → "bicycle"  
    """
    instruction = instruction.lower().strip()
    
    # Common patterns
    patterns = [
        r'(?:containing|with|showing|of)\s+(?:a\s+|an\s+)?(.+?)(?:\.|$)',
        r'(?:select|click|choose).*?(?:images?|squares?|tiles?)\s+(?:containing|with|of|showing)\s+(?:a\s+|an\s+)?(.+?)(?:\.|$)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, instruction)
        if match:
            obj = match.group(1).strip().rstrip('.')
            if obj:
                return obj
    
    # If no pattern matched, use the last noun-like phrase
    words = instruction.split()
    if len(words) >= 2:
        return " ".join(words[-2:]).rstrip('.')
    
    return instruction


def _screenshot_grid(frame) -> Optional[bytes]:
    """Take a screenshot of the hCaptcha image grid."""
    try:
        # Try to screenshot just the grid area
        grid_selectors = [
            '.task-image',
            '.challenge-container',
            '.task-grid', 
            '.image-wrapper',
            'body',  # fallback: entire frame
        ]
        
        for sel in grid_selectors:
            try:
                el = frame.locator(sel)
                if el.count() > 0:
                    screenshot = el.first.screenshot()
                    if screenshot and len(screenshot) > 1000:  # valid image
                        return screenshot
            except Exception:
                continue
        
        # Ultimate fallback: screenshot the entire page at the frame area
        # (frame.screenshot() not available in Playwright, use page)
        return None
    except Exception:
        return None


def _ask_gemini_which_tiles(grid_screenshot: bytes, target_object: str, full_instruction: str) -> list[int]:
    """Send the grid screenshot to Gemini Vision and ask which tiles to click.
    
    Returns a list of tile numbers (1-indexed) that contain the target object.
    hCaptcha typically shows 3x3=9 or 4x4=16 tiles.
    """
    try:
        from google import genai
        from google.genai import types
        
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        prompt = f"""You are solving an image CAPTCHA challenge. The challenge instruction says: "{full_instruction}"

You need to identify which image tiles in this grid contain "{target_object}".

The grid is typically 3x3 (9 tiles) or 4x4 (16 tiles), numbered left-to-right, top-to-bottom:
- 3x3 grid: tiles numbered 1-9
  Row 1: [1][2][3]
  Row 2: [4][5][6]
  Row 3: [7][8][9]
  
- 4x4 grid: tiles numbered 1-16
  Row 1: [1][2][3][4]
  Row 2: [5][6][7][8]
  Row 3: [9][10][11][12]
  Row 4: [13][14][15][16]

Look at the image grid and determine which tiles clearly contain "{target_object}" or a recognizable part of "{target_object}".

IMPORTANT RULES:
- Only select tiles where you are CONFIDENT the target object is present
- If unsure about a tile, do NOT select it
- First determine if it's a 3x3 or 4x4 grid
- Return ONLY the tile numbers as a comma-separated list
- If no tiles contain the target, return "none"
- Example response: "1,4,7" or "2,5,6,8" or "none"

Your response (ONLY numbers, comma-separated):"""

        image_part = types.Part.from_bytes(data=grid_screenshot, mime_type='image/png')
        
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[image_part, prompt],
        )
        
        result_text = response.text.strip()
        print(f"      🤖 Gemini response: '{result_text}'")
        
        # Parse the response into tile numbers
        if "none" in result_text.lower():
            return []
        
        # Extract all numbers from the response
        numbers = re.findall(r'\d+', result_text)
        tiles = [int(n) for n in numbers if 1 <= int(n) <= 16]
        
        return tiles
        
    except Exception as e:
        print(f"      ⚠️ Gemini Vision error: {str(e)[:80]}")
        return []


def _click_tiles(frame, tile_numbers: list[int]):
    """Click the specified tiles in the hCaptcha grid.
    
    Tiles are numbered 1-indexed, left-to-right, top-to-bottom.
    """
    try:
        # hCaptcha grid cells are typically in .task-image elements or similar
        cell_selectors = [
            '.task-image .image',
            '.task-image',
            '.image-wrapper .image',
            '.challenge-answer .cell',
            '[class*="cell"]',
            '[class*="task"] [class*="image"]',
        ]
        
        cells = None
        for sel in cell_selectors:
            cells_loc = frame.locator(sel)
            count = cells_loc.count()
            if count >= 9:  # at least a 3x3 grid
                cells = cells_loc
                break
        
        if not cells:
            # Fallback: try to find clickable divs/imgs in the grid
            cells = frame.locator('.task-grid div.cell, .task div[role="button"], .challenge div.border')
            if cells.count() < 9:
                print(f"      ⚠️ Could only find {cells.count()} cells (expected 9+)")
                return
        
        total_cells = cells.count()
        print(f"      📊 Grid has {total_cells} cells")
        
        for tile_num in tile_numbers:
            idx = tile_num - 1  # convert to 0-indexed
            if 0 <= idx < total_cells:
                try:
                    cells.nth(idx).click()
                    time.sleep(0.3)  # small delay between clicks (human-like)
                except Exception:
                    pass
    except Exception as e:
        print(f"      ⚠️ Click error: {str(e)[:60]}")


def _click_verify(frame):
    """Click the Verify/Submit button in the hCaptcha frame."""
    try:
        verify_selectors = [
            'button.button-submit',
            '.verify-button',
            'button:has-text("Verify")',
            'button:has-text("Submit")',
            'button:has-text("Check")',
            '.submit-button',
        ]
        for sel in verify_selectors:
            try:
                btn = frame.locator(sel)
                if btn.count() > 0 and btn.first.is_visible():
                    btn.first.click()
                    return
            except Exception:
                continue
    except Exception:
        pass


def _click_skip(frame) -> bool:
    """Click the Skip button if available (some challenges allow skipping)."""
    try:
        skip = frame.locator('button:has-text("Skip"), .button-skip, a:has-text("Skip")')
        if skip.count() > 0:
            skip.first.click()
            return True
    except Exception:
        pass
    return False
