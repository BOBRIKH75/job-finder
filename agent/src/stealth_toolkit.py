"""Unified stealth browser toolkit — 7 anti-detection tools with auto-fallback.

Tools (in fallback order):
1. SeleniumBase UC Mode — patched Selenium, hides automation fingerprints
2. Playwright + Stealth — spoofs navigator.webdriver, canvas, WebGL
3. Camoufox — Firefox-based stealth browser
4. Nodriver — lightweight CDP without ChromeDriver
5. curl_cffi — HTTP client mimicking real browser TLS fingerprints
6. FlareSolverr — Docker proxy that solves Cloudflare challenges
7. cloudflare-bypass-2026 — SeleniumBase UC + proxy rotation + cookie export
"""
import asyncio, json, logging, time, random, tempfile
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class StealthResult:
    success: bool
    tool: str
    html: str = ""
    cookies: list[dict] = field(default_factory=list)
    status_code: int = 0
    error: str = ""
    elapsed: float = 0.0


# ─── 1. SeleniumBase UC Mode ────────────────────────────────────────

def fetch_seleniumbase_uc(url: str, headless: bool = True, **kw) -> StealthResult:
    start = time.time()
    try:
        from seleniumbase import SB
        with SB(uc=True, headless=headless, test=True) as sb:
            sb.uc_open_with_reconnect(url, reconnect_time=30)
            time.sleep(random.uniform(2, 4))
            return StealthResult(True, "seleniumbase_uc", sb.get_page_source(),
                                 sb.get_cookies(), 200, elapsed=time.time() - start)
    except Exception as e:
        return StealthResult(False, "seleniumbase_uc", error=str(e), elapsed=time.time() - start)


# ─── 2. Playwright + Stealth ────────────────────────────────────────

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}};
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
const origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (p) =>
    p.name === 'notifications' ? Promise.resolve({state: Notification.permission}) : origQuery(p);
"""

def fetch_playwright_stealth(url: str, headless: bool = False, **kw) -> StealthResult:
    """Playwright + stealth JS injection.
    
    Runs in a daemon thread to avoid 'Playwright Sync API inside asyncio loop' error.
    """
    import threading

    start = time.time()
    _result: list[StealthResult] = []

    def _run():
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless)
                ctx = browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                    viewport={"width": 1920, "height": 1080}, locale="en-US",
                )
                ctx.add_init_script(STEALTH_JS)
                page = ctx.new_page()
                resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(random.randint(2000, 4000))
                html = page.content()
                cookies = [dict(c) for c in ctx.cookies()]
                status = resp.status if resp else 0
                browser.close()
                _result.append(StealthResult(status < 400, "playwright_stealth", html, cookies, status, elapsed=time.time() - start))
        except Exception as e:
            _result.append(StealthResult(False, "playwright_stealth", error=str(e), elapsed=time.time() - start))

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=45)

    if _result:
        return _result[0]
    return StealthResult(False, "playwright_stealth", error="Timed out (45s)", elapsed=time.time() - start)


# ─── 3. Camoufox ────────────────────────────────────────────────────

def fetch_camoufox(url: str, headless: bool = True, **kw) -> StealthResult:
    """Firefox-based stealth fetch.

    The sync Camoufox API breaks when called from inside an asyncio event loop
    ("Playwright Sync API inside asyncio loop").  Fix: run the async API in a
    fresh daemon thread that owns its own event loop — completely isolated from
    whatever loop the caller is running.
    """
    import asyncio
    import threading

    start = time.time()
    _result: list[StealthResult] = []

    async def _run() -> None:
        try:
            from camoufox.async_api import AsyncCamoufox
            async with AsyncCamoufox(headless=headless) as browser:
                page = await browser.new_page()
                resp = await page.goto(url, timeout=30000)
                await asyncio.sleep(random.uniform(2, 4))
                html = await page.content()
                ctx_cookies = await browser.contexts[0].cookies() if browser.contexts else []
                cookies = [dict(c) for c in ctx_cookies]
                status = resp.status if resp else 0
                _result.append(StealthResult(
                    status < 400, "camoufox", html, cookies, status,
                    elapsed=time.time() - start,
                ))
        except Exception as exc:
            _result.append(StealthResult(False, "camoufox", error=str(exc),
                                         elapsed=time.time() - start))

    def _thread_main() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()

    t = threading.Thread(target=_thread_main, daemon=True)
    t.start()
    t.join(timeout=45)

    if _result:
        return _result[0]
    return StealthResult(False, "camoufox", error="timeout after 45s",
                         elapsed=time.time() - start)


# ─── 4. Nodriver ─────────────────────────────────────────────────────

def fetch_nodriver(url: str, headless: bool = True, **kw) -> StealthResult:
    start = time.time()
    try:
        import nodriver as uc

        async def _run():
            browser = await uc.start(headless=headless)
            page = await browser.get(url)
            await asyncio.sleep(random.uniform(2, 4))
            html = await page.get_content()
            cookies = await browser.cookies.get_all()
            browser.stop()
            return html, [c.__dict__ if hasattr(c, '__dict__') else {} for c in (cookies or [])]

        loop = asyncio.new_event_loop()
        html, cookies = loop.run_until_complete(_run())
        loop.close()
        return StealthResult(bool(html), "nodriver", html, cookies, 200, elapsed=time.time() - start)
    except Exception as e:
        return StealthResult(False, "nodriver", error=str(e), elapsed=time.time() - start)


# ─── 5. curl_cffi ───────────────────────────────────────────────────

def fetch_curl_cffi(url: str, **kw) -> StealthResult:
    start = time.time()
    try:
        from curl_cffi import requests as cffi_req
        resp = cffi_req.get(url, impersonate="chrome", timeout=30)
        cookies = [{"name": k, "value": v} for k, v in resp.cookies.items()]
        return StealthResult(resp.status_code < 400, "curl_cffi", resp.text, cookies, resp.status_code, elapsed=time.time() - start)
    except Exception as e:
        return StealthResult(False, "curl_cffi", error=str(e), elapsed=time.time() - start)


# ─── 6. FlareSolverr ────────────────────────────────────────────────

def fetch_flaresolverr(url: str, flaresolverr_url: str = "http://localhost:8191/v1", **kw) -> StealthResult:
    start = time.time()
    try:
        import httpx
        resp = httpx.post(flaresolverr_url, json={"cmd": "request.get", "url": url, "maxTimeout": 60000}, timeout=90)
        data = resp.json()
        if data.get("status") == "ok":
            sol = data["solution"]
            return StealthResult(True, "flaresolverr", sol.get("response", ""), sol.get("cookies", []), sol.get("status", 200), elapsed=time.time() - start)
        return StealthResult(False, "flaresolverr", error=data.get("message", "unknown"), elapsed=time.time() - start)
    except Exception as e:
        return StealthResult(False, "flaresolverr", error=str(e), elapsed=time.time() - start)


# ─── 7. Cloudflare Bypass 2026 ──────────────────────────────────────

def fetch_cf_bypass(url: str, headless: bool = True, proxy: str = None, **kw) -> StealthResult:
    start = time.time()
    try:
        from seleniumbase import SB
        sb_args = dict(uc=True, headless=headless, test=True)
        if proxy:
            sb_args["proxy"] = proxy
        # Use variables outside the with block — SB context manager swallows exceptions
        # silently (it's a pytest plugin), so the function would return None without this.
        _html: str | None = None
        _cookies: list = []
        with SB(**sb_args) as sb:
            try:
                sb.uc_open_with_reconnect(url, reconnect_time=10)
                for _ in range(3):
                    time.sleep(3)
                    src = sb.get_page_source()
                    if "Just a moment" not in src and "Checking your browser" not in src:
                        break
                    try:
                        sb.uc_gui_click_captcha()
                    except Exception:
                        pass
                _html = sb.get_page_source()
                _cookies = sb.get_cookies()
            except Exception:
                pass  # SB logs the exception itself; we fall through to the None check below
        if _html is not None:
            cfile = Path(tempfile.gettempdir()) / "cf_cookies.txt"
            lines = ["# Netscape HTTP Cookie File"]
            for c in _cookies:
                d = c.get("domain", "")
                lines.append(f"{d}\tTRUE\t{c.get('path','/')}\t{'TRUE' if c.get('secure') else 'FALSE'}\t0\t{c['name']}\t{c['value']}")
            cfile.write_text("\n".join(lines))
            return StealthResult("Just a moment" not in _html, "cf_bypass", _html, _cookies, 200, elapsed=time.time() - start)
        return StealthResult(False, "cf_bypass", error="SB failed to fetch page", elapsed=time.time() - start)
    except Exception as e:
        return StealthResult(False, "cf_bypass", error=str(e), elapsed=time.time() - start)


# ─── 8. sarperavci Docker service (free, unlimited, GitHub Actions sidecar) ──

def fetch_sarperavci(url: str, **kw) -> StealthResult:
    """Fetch via sarperavci/CloudflareBypassForScraping Docker service.

    Runs as a GitHub Actions service container on CF_BYPASS_URL (default
    http://localhost:8000).  Uses a real Firefox browser inside xvfb to
    bypass Cloudflare — returns cookies + HTML.  100 % free, no API key.
    """
    import os
    base = os.environ.get("CF_BYPASS_URL", "")
    if not base:
        return StealthResult(False, "sarperavci", error="CF_BYPASS_URL not set")
    start = time.time()
    try:
        import requests as _req
        # /html returns the full page after Cloudflare bypass
        resp = _req.get(f"{base}/html", params={"url": url}, timeout=60)
        html = resp.text
        ua = resp.headers.get("x-cf-bypasser-user-agent", "")
        # /cookies returns cf_clearance + user-agent
        cr = _req.get(f"{base}/cookies", params={"url": url}, timeout=60).json()
        cookies = [{"name": k, "value": v, "domain": url.split("/")[2]}
                   for k, v in cr.get("cookies", {}).items()]
        blocked = any(s in html.lower() for s in ["just a moment", "checking your browser", "access denied"])
        return StealthResult(
            not blocked, "sarperavci", html, cookies,
            resp.status_code, elapsed=time.time() - start,
        )
    except Exception as e:
        return StealthResult(False, "sarperavci", error=str(e), elapsed=time.time() - start)


# ─── Auto-fallback chain ────────────────────────────────────────────

TOOL_CHAIN = [
    ("curl_cffi", fetch_curl_cffi),
    ("camoufox", fetch_camoufox),           # Firefox-based stealth — was defined but never wired
    ("playwright_stealth", fetch_playwright_stealth),
    ("seleniumbase_uc", fetch_seleniumbase_uc),
    ("nodriver", fetch_nodriver),
    ("flaresolverr", fetch_flaresolverr),
    ("sarperavci", fetch_sarperavci),
    ("cf_bypass", fetch_cf_bypass),
]


def stealth_fetch(url: str, tools: list[str] = None, headless: bool = True, db=None) -> StealthResult:
    """Fetch URL with auto-fallback through stealth tools.
    
    Smart mode (when db provided):
    - Checks memory for best tool for this domain
    - Tries proven tool FIRST (skips known-broken ones)
    - Learns from success/failure for next run
    """
    from urllib.parse import urlparse
    domain = urlparse(url).netloc.replace("www.", "")
    
    # Smart tool ordering if memory available
    if db:
        try:
            from .learning_engine import get_smart_tool_order, learn_stealth_success, learn_stealth_failure
            default_names = [n for n, _ in TOOL_CHAIN]
            if tools:
                default_names = [n for n in default_names if n in tools]
            smart_order = get_smart_tool_order(db, domain, default_names)
            chain = [(n, f) for n, f in TOOL_CHAIN if n in smart_order]
            # Sort chain by smart_order position
            chain.sort(key=lambda x: smart_order.index(x[0]) if x[0] in smart_order else 999)
            if smart_order != default_names:
                log.info(f"🧠 Smart order for {domain}: {smart_order[:4]}")
        except Exception as e:
            log.debug(f"Memory lookup failed ({e}), using default chain")
            chain = TOOL_CHAIN if not tools else [(n, f) for n, f in TOOL_CHAIN if n in tools]
    else:
        chain = TOOL_CHAIN if not tools else [(n, f) for n, f in TOOL_CHAIN if n in tools]
    
    last = None
    for name, func in chain:
        log.info(f"Trying {name} for {url}")
        result = func(url, headless=headless)
        last = result
        if result.success:
            log.info(f"✅ {name} succeeded in {result.elapsed:.1f}s")
            # Learn: this tool works for this domain
            if db:
                try:
                    learn_stealth_success(db, domain, name, result.elapsed * 1000)
                except Exception:
                    pass
            return result
        log.warning(f"❌ {name} failed: {result.error}")
        # Learn: this tool failed for this domain
        if db:
            try:
                learn_stealth_failure(db, domain, name, result.error)
            except Exception:
                pass
    return last or StealthResult(False, "none", error="All tools failed")


def list_available_tools() -> list[dict]:
    """Check which stealth tools are importable."""
    checks = [
        ("curl_cffi", "curl_cffi", "curl_cffi — browser TLS mimicry"),
        ("sarperavci", "requests", "sarperavci Docker — free CF bypass (needs CF_BYPASS_URL)"),
        ("seleniumbase_uc", "seleniumbase", "SeleniumBase UC Mode (70-90%)"),
        ("playwright_stealth", "playwright", "Playwright + Stealth JS (60-80%)"),
        ("camoufox", "camoufox", "Camoufox — Firefox stealth"),
        ("nodriver", "nodriver", "Nodriver — CDP without ChromeDriver"),
        ("flaresolverr", "httpx", "FlareSolverr (needs Docker container)"),
        ("cf_bypass", "seleniumbase", "CF Bypass 2026 — UC + proxy + cookies"),
    ]
    out = []
    for name, pkg, desc in checks:
        try:
            __import__(pkg)
            out.append({"name": name, "available": True, "description": desc})
        except Exception:
            out.append({"name": name, "available": False, "description": desc})
    return out
