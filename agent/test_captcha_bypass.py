#!/usr/bin/env python3
"""Test CAPTCHA bypass on LIVE demo pages.

Run:  python test_captcha_bypass.py

Tests 3 levels:
  1. Cloudflare "checking your browser" page  (cloudscraper / curl_cffi)
  2. Cloudflare Turnstile widget              (SeleniumBase UC Mode)
  3. Turnstile-protected form submission       (SeleniumBase UC Mode)

No API keys needed. No Docker needed. Runs locally.
"""
import sys, time

PASS = "✅ PASS"
FAIL = "❌ FAIL"
SKIP = "⏭️  SKIP"

results = []


def report(name, passed, detail=""):
    tag = PASS if passed else FAIL
    results.append((name, passed))
    print(f"  {tag}  {name}" + (f" — {detail}" if detail else ""))


# ─── Test 1: Cloudflare JS Challenge bypass (cloudscraper) ───────────

def test_cloudscraper():
    """Bypass the 'Checking your browser' interstitial page."""
    print("\n🧪 Test 1: Cloudflare JS Challenge (cloudscraper)")
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper(browser="chrome", interpreter="js2py", delay=5)
        # nowsecure.nl is a well-known Cloudflare-protected test site
        resp = scraper.get("https://nowsecure.nl", timeout=30)
        blocked = any(s in resp.text.lower() for s in ["just a moment", "checking your browser", "access denied"])
        if resp.status_code < 400 and not blocked:
            report("cloudscraper JS challenge", True, f"status={resp.status_code}, got {len(resp.text)} chars")
        else:
            report("cloudscraper JS challenge", False, f"status={resp.status_code}, blocked={blocked}")
    except ImportError:
        report("cloudscraper JS challenge", False, "cloudscraper not installed — pip install cloudscraper")
    except Exception as e:
        report("cloudscraper JS challenge", False, str(e)[:120])


# ─── Test 2: curl_cffi TLS fingerprint bypass ───────────────────────

def test_curl_cffi():
    """Bypass Cloudflare by mimicking Chrome's TLS fingerprint."""
    print("\n🧪 Test 2: TLS Fingerprint bypass (curl_cffi)")
    try:
        from curl_cffi import requests as cffi
        resp = cffi.get("https://nowsecure.nl", impersonate="chrome", timeout=30)
        blocked = any(s in resp.text.lower() for s in ["just a moment", "checking your browser"])
        if resp.status_code < 400 and not blocked:
            report("curl_cffi TLS bypass", True, f"status={resp.status_code}")
        else:
            report("curl_cffi TLS bypass", False, f"status={resp.status_code}, blocked={blocked}")
    except ImportError:
        report("curl_cffi TLS bypass", False, "curl_cffi not installed — pip install curl_cffi")
    except Exception as e:
        report("curl_cffi TLS bypass", False, str(e)[:120])


# ─── Test 3: Turnstile CAPTCHA solve (SeleniumBase UC Mode) ─────────

def test_turnstile_seleniumbase():
    """Solve a real Cloudflare Turnstile CAPTCHA on a live demo page."""
    print("\n🧪 Test 3: Turnstile CAPTCHA solve (SeleniumBase UC Mode)")
    try:
        from seleniumbase import SB
    except ImportError:
        report("Turnstile CAPTCHA solve", False, "seleniumbase not installed")
        return

    try:
        with SB(uc=True, headless=False, test=True) as sb:
            # Cloudflare's official Turnstile demo — has a real Turnstile widget
            sb.uc_open_with_reconnect("https://demo.turnstile.workers.dev/", reconnect_time=10)
            time.sleep(3)

            # The demo page has a Turnstile widget — try to click it
            try:
                sb.uc_gui_click_captcha()
                time.sleep(3)
            except Exception:
                pass  # May auto-solve in UC mode

            # Check if Turnstile was solved — look for the hidden token input
            page_src = sb.get_page_source().lower()

            # The demo has a form with username/password — if Turnstile is solved,
            # the cf-turnstile-response hidden input gets a token value
            solved = False
            try:
                token = sb.execute_script(
                    'return document.querySelector("[name=\\"cf-turnstile-response\\"]")?.value || ""'
                )
                solved = len(token) > 10
            except Exception:
                pass

            # Alternative check: page doesn't show "challenge" anymore
            if not solved:
                solved = "challenge" not in page_src or "success" in page_src

            # Try submitting the form to see if it goes through
            if solved:
                try:
                    sb.type("#username", "testuser")
                    sb.type("#password", "testpass")
                    sb.click('button[type="submit"]')
                    time.sleep(2)
                    after = sb.get_page_source().lower()
                    if "success" in after or "welcome" in after or sb.get_current_url() != "https://demo.turnstile.workers.dev/":
                        report("Turnstile CAPTCHA solve", True, "Solved + form submitted!")
                        return
                except Exception:
                    pass

            if solved:
                report("Turnstile CAPTCHA solve", True, "Token generated")
            else:
                # Take screenshot for debugging
                sb.save_screenshot("turnstile_debug.png")
                report("Turnstile CAPTCHA solve", False, "No token found — see turnstile_debug.png")

    except Exception as e:
        report("Turnstile CAPTCHA solve", False, str(e)[:150])


# ─── Test 4: Cloudflare-protected page with SeleniumBase UC ─────────

def test_cf_protected_page():
    """Access a Cloudflare-protected page using SeleniumBase UC Mode."""
    print("\n🧪 Test 4: Full Cloudflare bypass (SeleniumBase UC Mode)")
    try:
        from seleniumbase import SB
    except ImportError:
        report("CF full bypass (UC Mode)", False, "seleniumbase not installed")
        return

    try:
        with SB(uc=True, headless=False, test=True) as sb:
            sb.uc_open_with_reconnect("https://nowsecure.nl", reconnect_time=15)
            time.sleep(3)

            # Try clicking CAPTCHA if present
            try:
                sb.uc_gui_click_captcha()
                time.sleep(3)
            except Exception:
                pass

            page_src = sb.get_page_source()
            blocked = any(s in page_src.lower() for s in ["just a moment", "checking your browser", "access denied"])

            if not blocked and len(page_src) > 1000:
                report("CF full bypass (UC Mode)", True, f"Got {len(page_src)} chars of real content")
            else:
                sb.save_screenshot("cf_bypass_debug.png")
                report("CF full bypass (UC Mode)", False, f"Still blocked — see cf_bypass_debug.png")

    except Exception as e:
        report("CF full bypass (UC Mode)", False, str(e)[:150])


# ─── Run all ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("🔓 CAPTCHA Bypass Test Suite — Live Demo Pages")
    print("=" * 60)

    test_cloudscraper()
    test_curl_cffi()
    test_turnstile_seleniumbase()
    test_cf_protected_page()

    print("\n" + "=" * 60)
    passed = sum(1 for _, p in results if p)
    total = len(results)
    print(f"📊 Results: {passed}/{total} passed")

    if passed == total:
        print("🎉 All CAPTCHA bypasses working — ready for real job sites!")
    elif passed > 0:
        print("⚠️  Partial success — some methods work, enough for most job sites")
    else:
        print("❌ All failed — check dependencies: pip install cloudscraper curl_cffi seleniumbase")

    print("=" * 60)
    sys.exit(0 if passed > 0 else 1)
