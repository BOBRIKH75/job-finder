"""Refresh DICE_COOKIES / INDEED_COOKIES GitHub secrets from the user's REAL logged-in Chrome.

Why: the bots' saved sessions expire (Indeed ~12 days, Dice ~weeks) and the auto-login paths
can't pass Google SSO / passkeys. The user's everyday Chrome stays logged in, so we read its
cookies over the local DevTools port (no keychain decryption needed) and push them as secrets.

Works on any Mac where Chrome has remote debugging enabled (chrome://inspect -> "Allow remote
debugging", or Chrome started with --remote-debugging-port). Reads the port from
DevToolsActivePort, so nothing is hardcoded.

Usage:
    python3 agent/refresh_session_secrets.py            # check + push both
    python3 agent/refresh_session_secrets.py --dry-run  # check only, push nothing
    python3 agent/refresh_session_secrets.py --site dice
"""
import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

REPO = os.environ.get("JOB_FINDER_REPO", "BOBRIKH75/job-finder")
CHROME_DIRS = [
    "~/Library/Application Support/Google/Chrome",
    "~/Library/Application Support/Google/Chrome Beta",
    "~/.config/google-chrome",
]
# IP-bound Cloudflare cookies: never ship them; the runner earns its own on its own IP.
IP_BOUND = {"cf_clearance", "__cf_bm", "_cfuvid", "__cflb"}
SITES = {
    # site: (domain match, secret name, cookies that prove a logged-in session)
    "dice": ("dice.com", "DICE_COOKIES", {"access", "refreshToken", "identity"}),
    "indeed": ("indeed.com", "INDEED_COOKIES",
               {"__Secure-PassportAuthProxy-RefreshToken", "PPID", "SOCK"}),
}
MAX_SECRET_CHARS = 48000


def _devtools_ws() -> str:
    for d in CHROME_DIRS:
        path = os.path.join(os.path.expanduser(d), "DevToolsActivePort")
        if os.path.isfile(path):
            port, ws_path = open(path).read().split()[:2]
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3)
            except Exception:
                pass  # newer Chrome (autoConnect) hides /json; websocket still works
            return f"ws://127.0.0.1:{port}{ws_path}"
    sys.exit("no DevToolsActivePort: enable chrome://inspect -> 'Allow remote debugging' in Chrome")


async def _all_cookies(ws_url: str) -> list:
    import websockets

    async with websockets.connect(ws_url, max_size=50_000_000, open_timeout=10) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Storage.getCookies"}))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if msg.get("id") == 1:
                if "error" in msg:
                    sys.exit(f"CDP error: {msg['error']}")
                return msg["result"]["cookies"]


def _to_playwright(c: dict) -> dict:
    out = {
        "name": c["name"],
        "value": c["value"],
        "domain": c["domain"],
        "path": c.get("path", "/"),
        "expires": c.get("expires", -1) if not c.get("session") else -1,
        "httpOnly": bool(c.get("httpOnly")),
        "secure": bool(c.get("secure")),
    }
    if c.get("sameSite") in ("Strict", "Lax", "None"):
        out["sameSite"] = c["sameSite"]
    return out


def _push(secret: str, cookies: list, dry_run: bool) -> bool:
    enc = base64.b64encode(json.dumps(cookies).encode()).decode()
    if len(enc) > MAX_SECRET_CHARS:
        print(f"  {secret}: {len(enc)} chars > limit, dropping analytics cookies")
        keep = [c for c in cookies if not c["name"].startswith(("_ga", "_gcl", "_fbp", "_uet", "__ar", "ph_"))]
        enc = base64.b64encode(json.dumps(keep).encode()).decode()
    if dry_run:
        print(f"  {secret}: dry-run, would push {len(cookies)} cookies ({len(enc)} chars)")
        return True
    r = subprocess.run(["gh", "secret", "set", secret, "--body", enc, "--repo", REPO],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  {secret}: gh secret set FAILED: {r.stderr.strip()[:200]}")
        return False
    print(f"  {secret}: pushed {len(cookies)} cookies")
    return True


def _all_cookies_sync() -> list:
    """Run the CDP read in its own thread: callers may already be inside an event loop
    (Playwright's sync API runs one), where asyncio.run() is not allowed."""
    from concurrent.futures import ThreadPoolExecutor

    ws = _devtools_ws()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(_all_cookies(ws))).result(timeout=30)


def local_chrome_cookies(site: str) -> list:
    """Logged-in cookies for 'dice'/'indeed' from this machine's Chrome, or [] (never raises).
    Used by the appliers when PREFER_LOCAL_CHROME=1 so a run never depends on a stale secret."""
    domain, _secret, proof = SITES[site]
    for attempt in range(2):  # one retry: a DevTools connection can clash with another client
        try:
            cookies = _all_cookies_sync()
            sel = [_to_playwright(c) for c in cookies
                   if domain in c["domain"] and c["name"] not in IP_BOUND]
            if proof & {c["name"] for c in sel}:
                return sel
        except BaseException:  # SystemExit from _devtools_ws when Chrome isn't debuggable
            pass
        time.sleep(2)
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--site", choices=sorted(SITES), action="append")
    args = ap.parse_args()

    cookies = asyncio.run(_all_cookies(_devtools_ws()))
    ok = True
    for site in args.site or sorted(SITES):
        domain, secret, proof = SITES[site]
        sel = [_to_playwright(c) for c in cookies
               if domain in c["domain"] and c["name"] not in IP_BOUND]
        names = {c["name"] for c in sel}
        if not proof & names:
            print(f"  {site}: NOT logged in in Chrome (none of {sorted(proof)}) -> log in, then re-run")
            ok = False
            continue
        ok = _push(secret, sel, args.dry_run) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
