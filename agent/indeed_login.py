#!/usr/bin/env python3
"""Automatic Indeed login for the self-hosted runner (no human).

Order: (1) already logged in via persistent profile -> done;
       (2) Indeed email one-time-code, code read from Gmail IMAP (GMAIL_USER/GMAIL_APP_PASSWORD);
       (3) 'Continue with Google' (works if the profile is signed into Google).
Prints only booleans/counts/URLs-without-query. Never prints codes, cookies or full emails.
Usable as a module (ensure_logged_in(page)) or standalone (python3 indeed_login.py)."""
import email as _email
import imaplib
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

sys.path.insert(0, '.')
sys.path.insert(0, 'src')

CHECK_URL = 'https://secure.indeed.com/settings/account'


def _short(url):
    return (url or '').split('?')[0][:80]


def is_logged_in(page) -> bool:
    """Logged in iff a protected account page does NOT bounce to the /auth sign-in page."""
    try:
        page.goto(CHECK_URL, wait_until='domcontentloaded', timeout=45000)
        time.sleep(4)
        _cf(page)
        u = (page.url or '').lower()
        ok = 'secure.indeed.com' in u and '/auth' not in u and 'login' not in u
        print(f"  \U0001F510 login check: {'LOGGED IN' if ok else 'LOGGED OUT'} at {_short(page.url)}")
        return ok
    except Exception as e:
        print(f"  \u26a0 login check error: {str(e)[:60]}")
        return False


def _cf(page):
    try:
        import submit_one as s1
        if s1.is_cloudflare(page):
            print("  \u2601 Cloudflare challenge on login page - waiting")
            s1._wait_out_cloudflare(page, 40)
    except Exception:
        pass


def _controls(page):
    """Safe debug: visible button/link/input labels (no values)."""
    try:
        return page.evaluate("""() => {
          const v = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
          const out = [];
          document.querySelectorAll('button,a,input').forEach(e => { if (!v(e)) return;
            const t = (e.innerText || e.getAttribute('aria-label') || e.type || '').trim().slice(0, 40);
            if (t) out.push(e.tagName.toLowerCase() + ':' + t); });
          return out.slice(0, 25);
        }""")
    except Exception:
        return []


def fetch_indeed_code(since_epoch, wait=90):
    """Poll Gmail for a FRESH Indeed sign-in code email (6 digits). Returns code or None."""
    user, pw = os.environ.get('GMAIL_USER', ''), os.environ.get('GMAIL_APP_PASSWORD', '')
    if not user or not pw:
        print("  \u26a0 no GMAIL creds in env")
        return None
    cutoff = datetime.fromtimestamp(since_epoch - 30, tz=timezone.utc)
    end = time.time() + wait
    while time.time() < end:
        try:
            m = imaplib.IMAP4_SSL('imap.gmail.com')
            m.login(user, pw)
            m.select('"[Gmail]/All Mail"')
            day = (datetime.now() - timedelta(days=1)).strftime('%d-%b-%Y')
            st, ids = m.search(None, f'(SINCE {day} FROM "indeed")')
            for mid in reversed(ids[0].split() if st == 'OK' and ids and ids[0] else []):
                st, d = m.fetch(mid, '(RFC822)')
                msg = _email.message_from_bytes(d[0][1])
                try:
                    dt = parsedate_to_datetime(msg.get('Date', ''))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        continue
                except Exception:
                    continue
                subj = str(_email.header.make_header(_email.header.decode_header(msg.get('Subject', ''))))
                body = ''
                for part in (msg.walk() if msg.is_multipart() else [msg]):
                    if part.get_content_type() in ('text/plain', 'text/html'):
                        body += part.get_payload(decode=True).decode('utf-8', 'ignore')
                body = re.sub(r'<[^>]+>', ' ', body)
                if not re.search(r'code|verify|sign.?in|log.?in', subj + ' ' + body[:400], re.I):
                    continue
                mm = re.search(r'(?<!\d)(\d{6})(?!\d)', subj) or re.search(r'(?<!\d)(\d{6})(?!\d)', body)
                if mm:
                    m.logout()
                    print("  \u2705 got fresh Indeed code from Gmail (hidden)")
                    return mm.group(1)
            m.logout()
        except Exception as e:
            print(f"  \u26a0 imap error: {str(e)[:50]}")
        time.sleep(5)
    print("  \u274c no fresh Indeed code email")
    return None


def _first(page, sels):
    for s in sels:
        try:
            l = page.locator(s).first
            if l.count() > 0 and l.is_visible():
                return l
        except Exception:
            continue
    return None


def _login_email_code(page) -> bool:
    em = os.environ.get('INDEED_EMAIL') or os.environ.get('GMAIL_USER', '')
    if not em:
        return False
    page.goto('https://secure.indeed.com/auth?hl=en_US&continue=https%3A%2F%2Fwww.indeed.com%2F',
              wait_until='domcontentloaded', timeout=45000)
    time.sleep(4)
    _cf(page)
    print("  login page controls:", _controls(page))
    box = _first(page, ['input[type="email"]', 'input[name="__email"]', 'input[id*="email" i]', 'input[type="text"]'])
    if not box:
        print("  \u26a0 no email box on login page")
        return False
    box.fill(em)
    t0 = time.time()
    btn = _first(page, ['button[type="submit"]', 'button:has-text("Continue")', 'button:has-text("Sign in")'])
    (btn.click() if btn else box.press('Enter'))
    time.sleep(5)
    _cf(page)
    print("  after email controls:", _controls(page), _short(page.url))
    # Password screen -> ask for a one-time code instead
    alt = _first(page, ['a:has-text("code")', 'button:has-text("code")', 'a:has-text("Sign in with a code")',
                        'button:has-text("Sign in with a code")', 'a:has-text("Email me")', 'button:has-text("Email me")'])
    if alt and not _first(page, ['input[autocomplete="one-time-code"]', 'input[name*="code" i]']):
        alt.click()
        t0 = time.time()
        time.sleep(5)
        print("  after alt controls:", _controls(page), _short(page.url))
    cbox = _first(page, ['input[autocomplete="one-time-code"]', 'input[name*="code" i]',
                         'input[inputmode="numeric"]', 'input[id*="code" i]', 'input[type="tel"]'])
    if not cbox:
        print("  \u26a0 no code box (maybe password/captcha/google-only)")
        return False
    code = fetch_indeed_code(t0)
    if not code:
        return False
    cbox.fill(code)
    sb = _first(page, ['button[type="submit"]', 'button:has-text("Continue")', 'button:has-text("Verify")', 'button:has-text("Sign in")'])
    (sb.click() if sb else cbox.press('Enter'))
    time.sleep(7)
    _cf(page)
    nn = _first(page, ['button:has-text("Not now")', 'a:has-text("Not now")'])
    if nn:  # passkey upsell
        nn.click()
        time.sleep(3)
    print("  after code:", _short(page.url))
    return True


def _login_google(page) -> bool:
    page.goto('https://secure.indeed.com/auth?hl=en_US', wait_until='domcontentloaded', timeout=45000)
    time.sleep(4)
    g = _first(page, ['button:has-text("Google")', 'a:has-text("Google")', '[aria-label*="Google" i]',
                      '[data-tn-element*="google" i]', '[id*="google" i]'])
    if not g:
        print("  \u2139 no Google button")
        return False
    try:
        with page.context.expect_page(timeout=8000) as pop:
            g.click()
        pp = pop.value
        time.sleep(5)
        for sel in ('[data-identifier]', 'div[role="link"]', '[data-authuser]'):
            t = pp.locator(sel).first
            if t.count() > 0:
                t.click()
                break
        time.sleep(7)
    except Exception:
        time.sleep(6)
        for sel in ('[data-identifier]', 'div[role="link"]', '[data-authuser]'):
            try:
                t = page.locator(sel).first
                if t.count() > 0:
                    t.click()
                    break
            except Exception:
                pass
        time.sleep(6)
    return True


def import_from_real_chrome(page) -> bool:
    """Copy Indeed cookies from the Mac's REAL Chrome profiles (the user's own logged-in browser)
    into this context, one profile at a time, until the account page stops redirecting to /auth.
    Reports only profile names + counts. Keychain read happens in a thread with a timeout."""
    import glob
    import threading
    base = os.path.expanduser('~/Library/Application Support/Google/Chrome')
    files = sorted(glob.glob(base + '/*/Network/Cookies') + glob.glob(base + '/*/Cookies'))
    for f in files:
        name = f.split('/Chrome/')[1].split('/')[0]
        res = {}

        def work():
            try:
                import browser_cookie3
                cj = browser_cookie3.chrome(cookie_file=f, domain_name='indeed.com')
                res['c'] = [{'name': c.name, 'value': c.value, 'domain': c.domain, 'path': c.path or '/',
                             'secure': bool(c.secure), 'expires': c.expires or -1,
                             'sameSite': 'Lax'} for c in cj]
            except Exception as e:
                res['err'] = str(e)[:80]
        t = threading.Thread(target=work, daemon=True)
        t.start()
        t.join(40)
        cs = res.get('c') or []
        names = {c['name'] for c in cs}
        print(f"  \U0001F4C2 chrome profile '{name}': decrypted={len(cs)} err={res.get('err', 'timeout' if t.is_alive() else '')} "
              f"auth_names={sorted(n for n in names if n in ('CTK', 'PPID', 'SOCK', 'RF'))}")
        if not any(n in names for n in ('PPID', 'SOCK')):
            continue
        try:
            page.context.add_cookies(cs)
        except Exception as e:
            print('  \u26a0 add_cookies', str(e)[:60])
            continue
        if is_logged_in(page):
            print(f"  \u2705 logged in using real Chrome profile '{name}'")
            return True
        try:
            page.context.clear_cookies()
        except Exception:
            pass
    return False


def ensure_logged_in(page, tries=2) -> bool:
    """Return True when the page's browser context has a valid Indeed session."""
    if is_logged_in(page):
        return True
    for i in range(tries):
        print(f"  \U0001F511 auto-login attempt {i + 1}")
        for fn in (_login_email_code, _login_google):
            try:
                fn(page)
            except Exception as e:
                print(f"  \u26a0 {fn.__name__} error: {str(e)[:80]}")
            if is_logged_in(page):
                print(f"  \u2705 logged in via {fn.__name__}")
                return True
    # last resort only (macOS keychain usually blocks this on the runner)
    return import_from_real_chrome(page)


if __name__ == '__main__':
    try:
        from submit_one import _load_env
        _load_env()
    except Exception:
        pass
    from patchright.sync_api import sync_playwright
    prof = os.environ.get('INDEED_PROFILE_DIR') or os.path.expanduser('~/.cv-indeed-profile')
    os.makedirs(prof, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(user_data_dir=prof, channel='chrome', headless=False, no_viewport=True)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        ok = ensure_logged_in(pg)
        print('LOGIN_OK' if ok else 'LOGIN_FAILED')
        ctx.close()
    sys.exit(0 if ok else 1)
