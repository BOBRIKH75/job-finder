#!/usr/bin/env python3
"""
hCaptcha Solver — Token-based approach via solving service API.

How it works (proven approach used by thousands of automation tools):
1. Extract hCaptcha sitekey from the page DOM
2. Send sitekey + page URL to a solving service (2captcha or CapSolver)
3. Service solves the challenge using real humans or AI (takes 10-30s)
4. We get back a token string
5. Inject token into the page's h-captcha-response field
6. Call the hCaptcha callback function to notify the page

This avoids ALL problems with:
- Cross-origin iframe access (we never touch the iframe)
- Screenshot failures (no screenshots needed)
- Headless browser detection (solving happens server-side)
- CSS selector guessing (we only read data-sitekey attribute)

Supported services (configured via environment variables):
- CAPSOLVER_API_KEY → CapSolver (cheapest, ~$0.8/1000 solves)
- TWOCAPTCHA_API_KEY → 2Captcha (~$2.99/1000 solves)

If neither key is set, returns False (solver disabled).
"""

import os
import time
import json
import logging
from typing import Optional

import requests

# Gemini Flash free CAPTCHA solver (fallback when CapSolver has no balance)
try:
    from src.gemini_captcha_solver import solve_captcha_with_gemini
except ImportError:
    try:
        from gemini_captcha_solver import solve_captcha_with_gemini
    except ImportError:
        solve_captcha_with_gemini = None

logger = logging.getLogger(__name__)

# Service API keys (set as GitHub secrets)
CAPSOLVER_API_KEY = os.environ.get("CAPSOLVER_KEY", "")
TWOCAPTCHA_API_KEY = os.environ.get("TWOCAPTCHA_API_KEY", "")

# Timeouts
MAX_WAIT_SECONDS = 120  # max time to wait for solution
POLL_INTERVAL = 5       # seconds between polls


def solve_hcaptcha(page) -> bool:
    """Solve hCaptcha on the current page using token injection.
    
    Args:
        page: Playwright page object (sync API)
        
    Returns:
        True if solved successfully, False otherwise
    """
    if not CAPSOLVER_API_KEY and not TWOCAPTCHA_API_KEY:
        logger.info("      ⚠️ hCaptcha solver: no API key (CAPSOLVER_API_KEY or TWOCAPTCHA_API_KEY)")
        return False
    
    # Step 1: Extract sitekey from the page
    sitekey = _extract_sitekey(page)
    if not sitekey:
        logger.info("      ⚠️ hCaptcha solver: could not find sitekey on page")
        return False
    
    page_url = page.url
    logger.info(f"      🧩 hCaptcha: sitekey={sitekey[:12]}... url={page_url[:50]}")
    
    # Step 2: Get token from solving service
    token = None
    if CAPSOLVER_API_KEY:
        token = _solve_via_capsolver(sitekey, page_url)
    if not token and TWOCAPTCHA_API_KEY:
        token = _solve_via_2captcha(sitekey, page_url)
    
    if not token:
        logger.info("      ❌ hCaptcha: solving service failed to return token")
        # Fallback: try Gemini Flash visual solver (FREE)
        if solve_captcha_with_gemini:
            logger.info("      🤖 hCaptcha: trying Gemini Flash visual solver (free fallback)...")
            if solve_captcha_with_gemini(page, "hcaptcha"):
                return True
            logger.info("      ⚠️ Gemini visual solver also failed")
        return False
    
    logger.info(f"      🔑 hCaptcha: got token ({len(token)} chars)")
    
    # Step 3: Inject token into the page
    injected = _inject_token(page, token)
    if not injected:
        logger.info("      ❌ hCaptcha: token injection failed")
        return False
    
    logger.info("      ✅ hCaptcha: token injected successfully")
    return True


def _extract_sitekey(page) -> Optional[str]:
    """Extract the hCaptcha sitekey from the page DOM.
    
    The sitekey is always in the page HTML as a data attribute — no need to
    access cross-origin iframes.
    """
    try:
        sitekey = page.evaluate("""() => {
            // Method 1: data-sitekey on .h-captcha div
            const hc = document.querySelector('.h-captcha[data-sitekey], [data-hcaptcha-sitekey]');
            if (hc) return hc.dataset.sitekey || hc.dataset.hcaptchaSitekey || '';
            
            // Method 2: data-sitekey on any element
            const el = document.querySelector('[data-sitekey]');
            if (el) return el.dataset.sitekey || '';
            
            // Method 3: from hCaptcha script URL parameter
            const scripts = document.querySelectorAll('script[src*="hcaptcha.com"]');
            for (const s of scripts) {
                const m = s.src.match(/sitekey=([^&]+)/);
                if (m) return m[1];
            }
            
            // Method 4: from iframe src
            const iframes = document.querySelectorAll('iframe[src*="hcaptcha.com"]');
            for (const f of iframes) {
                const m = f.src.match(/sitekey=([^&]+)/);
                if (m) return m[1];
            }
            
            return '';
        }""")
        
        if sitekey and len(sitekey) > 10:
            return sitekey
    except Exception as e:
        logger.warning(f"      ⚠️ sitekey extraction error: {str(e)[:60]}")
    
    return None


def _solve_via_capsolver(sitekey: str, page_url: str) -> Optional[str]:
    """Solve hCaptcha using CapSolver API.
    
    Docs: https://docs.capsolver.com/guide/captcha/hcaptcha.html
    Cost: ~$0.8 per 1000 solves
    """
    # Dynamic disable: if already failed this session (no balance), don't retry
    if hasattr(_solve_via_capsolver, '_disabled') and _solve_via_capsolver._disabled:
        logger.info("      ⏭️ CapSolver disabled this session (no balance)")
        return None
    
    logger.info("      🔄 Trying CapSolver...")
    
    try:
        # Step 1: Create task
        create_resp = requests.post(
            "https://api.capsolver.com/createTask",
            json={
                "clientKey": CAPSOLVER_API_KEY,
                "task": {
                    "type": "HCaptchaTaskProxyless",
                    "websiteURL": page_url,
                    "websiteKey": sitekey,
                }
            },
            timeout=15
        )
        create_data = create_resp.json()
        
        if create_data.get("errorId", 1) != 0:
            error_msg = create_data.get("errorDescription", "unknown")
            logger.warning(f"      ⚠️ CapSolver createTask error: {error_msg}")
            # If balance/key issue — disable for entire session
            if "insufficient" in error_msg.lower() or "invalid" in error_msg.lower() or "denied" in error_msg.lower():
                _solve_via_capsolver._disabled = True
                logger.warning(f"      🚫 CapSolver DISABLED this session (no balance/invalid key)")
            return None
        
        task_id = create_data.get("taskId", "")
        if not task_id:
            return None
        
        # Step 2: Poll for result
        for _ in range(MAX_WAIT_SECONDS // POLL_INTERVAL):
            time.sleep(POLL_INTERVAL)
            
            result_resp = requests.post(
                "https://api.capsolver.com/getTaskResult",
                json={
                    "clientKey": CAPSOLVER_API_KEY,
                    "taskId": task_id,
                },
                timeout=10
            )
            result_data = result_resp.json()
            
            status = result_data.get("status", "")
            if status == "ready":
                solution = result_data.get("solution", {})
                token = solution.get("gRecaptchaResponse", "")
                if token and len(token) > 20:
                    return token
                return None
            elif status == "failed":
                logger.warning(f"      ⚠️ CapSolver task failed")
                return None
            # else: still processing, continue polling
        
        logger.warning("      ⚠️ CapSolver timeout")
        return None
        
    except requests.exceptions.RequestException as e:
        logger.warning(f"      ⚠️ CapSolver network error: {str(e)[:60]}")
        return None
    except Exception as e:
        logger.warning(f"      ⚠️ CapSolver error: {str(e)[:60]}")
        return None


def _solve_via_2captcha(sitekey: str, page_url: str) -> Optional[str]:
    """Solve hCaptcha using 2Captcha API.
    
    Docs: https://2captcha.com/2captcha-api#solving_hcaptcha
    Cost: ~$2.99 per 1000 solves
    """
    logger.info("      🔄 Trying 2Captcha...")
    
    try:
        # Step 1: Submit task
        submit_resp = requests.post(
            "https://2captcha.com/in.php",
            data={
                "key": TWOCAPTCHA_API_KEY,
                "method": "hcaptcha",
                "sitekey": sitekey,
                "pageurl": page_url,
                "json": "1",
            },
            timeout=15
        )
        submit_data = submit_resp.json()
        
        if submit_data.get("status") != 1:
            error_msg = submit_data.get("request", "unknown")
            logger.warning(f"      ⚠️ 2Captcha submit error: {error_msg}")
            return None
        
        captcha_id = submit_data.get("request", "")
        if not captcha_id:
            return None
        
        # Step 2: Poll for result (wait initial 15s — solving takes time)
        time.sleep(15)
        
        for _ in range(MAX_WAIT_SECONDS // POLL_INTERVAL):
            result_resp = requests.get(
                "https://2captcha.com/res.php",
                params={
                    "key": TWOCAPTCHA_API_KEY,
                    "action": "get",
                    "id": captcha_id,
                    "json": "1",
                },
                timeout=10
            )
            result_data = result_resp.json()
            
            if result_data.get("status") == 1:
                token = result_data.get("request", "")
                if token and len(token) > 20:
                    return token
                return None
            elif result_data.get("request") == "CAPCHA_NOT_READY":
                time.sleep(POLL_INTERVAL)
                continue
            else:
                error_msg = result_data.get("request", "unknown")
                logger.warning(f"      ⚠️ 2Captcha result error: {error_msg}")
                return None
        
        logger.warning("      ⚠️ 2Captcha timeout")
        return None
        
    except requests.exceptions.RequestException as e:
        logger.warning(f"      ⚠️ 2Captcha network error: {str(e)[:60]}")
        return None
    except Exception as e:
        logger.warning(f"      ⚠️ 2Captcha error: {str(e)[:60]}")
        return None


def _inject_token(page, token: str) -> bool:
    """Inject the solved token into the page's hCaptcha response fields.
    
    This is the standard token injection approach:
    1. Set the h-captcha-response textarea value
    2. Set iframe data-hcaptcha-response attribute
    3. Call the hCaptcha callback function (if registered)
    """
    try:
        result = page.evaluate("""(token) => {
            let injected = false;
            
            // Method 1: Set textarea value (standard hCaptcha response field)
            const textareas = document.querySelectorAll(
                '[name="h-captcha-response"], textarea[name*="hcaptcha"], [name="g-recaptcha-response"]'
            );
            for (const ta of textareas) {
                ta.value = token;
                // Dispatch events for React/Vue/Angular listeners
                ta.dispatchEvent(new Event('input', { bubbles: true }));
                ta.dispatchEvent(new Event('change', { bubbles: true }));
                injected = true;
            }
            
            // Method 2: Set iframe data attribute
            const iframes = document.querySelectorAll('iframe[data-hcaptcha-response]');
            for (const f of iframes) {
                f.setAttribute('data-hcaptcha-response', token);
                injected = true;
            }
            
            // Method 3: Call registered callback (this submits the form in most cases)
            // hCaptcha stores callbacks that fire when solved
            try {
                // Standard hCaptcha callback via widget
                if (window.hcaptcha) {
                    // Try to find the widget ID and set response
                    const widgetIds = Object.keys(window.hcaptcha._widgets || {});
                    if (widgetIds.length > 0) {
                        // Internal: set response on first widget
                        const widget = window.hcaptcha._widgets[widgetIds[0]];
                        if (widget && widget.response) {
                            widget.response = token;
                        }
                    }
                }
            } catch(e) {}
            
            // Method 4: Trigger onVerify callback if registered on .h-captcha element
            try {
                const hcDiv = document.querySelector('.h-captcha[data-callback]');
                if (hcDiv) {
                    const callbackName = hcDiv.dataset.callback;
                    if (callbackName && typeof window[callbackName] === 'function') {
                        window[callbackName](token);
                        injected = true;
                    }
                }
            } catch(e) {}
            
            return injected;
        }""", token)
        
        return result
        
    except Exception as e:
        logger.warning(f"      ⚠️ Token injection error: {str(e)[:60]}")
        return False
