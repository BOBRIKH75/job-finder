"""Watch Indeed Messages and alert Bob when a REAL person writes (interview, question, call).

Why: recruiters reply inside Indeed Messages, not Gmail. The reply tracker only read Gmail,
so a real interview request (Nov 17/19) sat unanswered for 6 days while reports said
"0 human replies". This closes that gap.

Sources for the session (first that works): INDEED_COOKIES secret (base64 JSON, CI),
or the local logged-in Chrome via DevTools (refresh_session_secrets helpers).

Alerts: email to GMAIL_USER (Gmail SMTP app password) + optional ntfy push (NTFY_TOPIC).
Dedup: data/indeed_inbox_seen.json (one alert per new message).

Usage:  python3 indeed_inbox_watch.py [--dry-run]
"""
import argparse
import base64
import hashlib
import json
import os
import re
import smtplib
import sys
import time
import urllib.request
from email.mime.text import MIMEText

SEEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "indeed_inbox_seen.json")
INBOX_URL = "https://messages.indeed.com/conversations"

# A human asking Bob to act: interview / schedule / call / question / rate / availability.
HUMAN_ASK = re.compile(
    r"interview|schedule|set ?up (a )?time|what days|availability|available|call you|"
    r"phone|chat|rate|resume|right to represent|rtr|\?|are you (open|interested)|"
    r"total experience|visa|work authori|when can you", re.I)
# Template / automated messages that only push Bob to another site.
AUTOMATED = re.compile(
    r"complete the application|please complete|we've sent you an email|thank you for applying"
    r"(?!.*(interview|schedule|call))|application process here|saw your message and is interested|"
    r"i consent|apply using this link", re.I)


def _load_cookies():
    env = os.environ.get("INDEED_COOKIES", "").strip()
    if env:
        return json.loads(base64.b64decode(env).decode() if not env.startswith("[") else env)
    try:
        import refresh_session_secrets as rss
        cs = rss._all_cookies_sync()
        return [rss._to_playwright(c) for c in cs
                if "indeed.com" in c["domain"] and c["name"] not in rss.IP_BOUND]
    except SystemExit:
        return []


def classify(snippet: str, awaiting: bool) -> str:
    """'human' = a person is waiting on Bob, 'auto' = template/redirect, 'other'."""
    s = snippet or ""
    if AUTOMATED.search(s) and not re.search(r"interview|schedule|call", s, re.I):
        return "auto"
    if HUMAN_ASK.search(s) or awaiting:
        return "human"
    return "other"


def read_inbox(cookies, headful: bool):
    try:
        from patchright.sync_api import sync_playwright
        kw = {"channel": "chrome"}
    except Exception:
        from playwright.sync_api import sync_playwright
        kw = {}
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=not headful, **kw)
        ctx = b.new_context()
        ctx.add_cookies(cookies)
        pg = ctx.new_page()
        pg.goto(INBOX_URL, wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(7000)
        url = pg.url
        text = pg.inner_text("body")
        b.close()
    if "Request Blocked" in text or "You have been blocked" in text:
        print("::warning::Indeed/Cloudflare blocked this browser (try headful / later)")
        return None
    if "login" in url.lower() or "auth" in url.lower() or "Messages" not in text:
        return None
    return parse_inbox(text)


_DATE = re.compile(r"^(Today|Yesterday|\d{1,2}:\d{2} ?[AP]M|[A-Z][a-z]{2} \d{1,2}(, \d{4})?)$")


def parse_inbox(text: str):
    """Parse the conversation list: <sender> <date> [<snippet>] [Awaiting response]."""
    lines = [l.strip() for l in text.splitlines() if l.strip() and l.strip() != "\xa0"]
    if "Inbox" in lines:
        lines = lines[lines.index("Inbox") + 1:]
    if "Welcome to Messages" in lines:
        lines = lines[:lines.index("Welcome to Messages")]
    is_date = lambda k: k < len(lines) and bool(_DATE.match(lines[k]))
    items, i = [], 0
    while i + 1 < len(lines):
        if not is_date(i + 1):
            i += 1
            continue
        item = {"sender": lines[i], "date": lines[i + 1], "snippet": "", "awaiting": False}
        j = i + 2
        if j < len(lines) and lines[j] != "Awaiting response" and not is_date(j + 1):
            item["snippet"] = lines[j]
            j += 1
        if j < len(lines) and lines[j] == "Awaiting response":
            item["awaiting"] = True
            j += 1
        items.append(item)
        i = j
    return items


def _key(m):
    return hashlib.sha1(f"{m['sender']}|{m['date']}|{m['snippet']}".encode()).hexdigest()[:16]


def alert(new_items, dry_run: bool):
    body = "Real people wrote to you on Indeed. Reply here: " + INBOX_URL + "\n\n" + "\n\n".join(
        f"- {m['sender']} ({m['date']}){' — AWAITING YOUR REPLY' if m['awaiting'] else ''}\n  {m['snippet'][:200]}"
        for m in new_items)
    subject = f"ACTION: {len(new_items)} Indeed recruiter message(s) waiting - {new_items[0]['sender']}"
    print(body)
    if dry_run:
        return
    user, pw = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
    if user and pw:
        msg = MIMEText(body)
        msg["Subject"], msg["From"], msg["To"] = subject, user, user
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
            s.starttls()
            s.login(user, pw)
            s.send_message(msg)
        print("  email alert sent")
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        try:  # HTTP headers must be latin-1; a failed push must never lose the email/dedup
            title = subject[:120].encode("latin-1", "replace").decode("latin-1")
            req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=body[:3500].encode(),
                                         headers={"Title": title, "Priority": "high"})
            urllib.request.urlopen(req, timeout=15)
            print("  ntfy push sent")
        except Exception as exc:
            print(f"::warning::ntfy push failed: {str(exc)[:80]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--all", action="store_true", help="alert on all human messages, ignore dedup")
    args = ap.parse_args()
    cookies = _load_cookies()
    if not cookies:
        print("::error::no Indeed cookies (INDEED_COOKIES secret or logged-in Chrome)")
        return 3
    items = read_inbox(cookies, headful=os.environ.get("HEADLESS") != "1")
    if items is None:
        print("::error::Indeed inbox not readable (session expired or blocked) — run: "
              "python3 agent/refresh_session_secrets.py --site indeed")
        return 3
    try:
        seen = set(json.load(open(SEEN_FILE)))
    except Exception:
        seen = set()
    human = [m for m in items if classify(m["snippet"], m["awaiting"]) == "human"]
    new = [m for m in human if args.all or _key(m) not in seen]
    print(f"inbox: {len(items)} conversations, {len(human)} from people, {len(new)} new")
    if not args.dry_run:  # save first: a failed alert must not cause a repeat every run
        os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
        json.dump(sorted(seen | {_key(m) for m in human}), open(SEEN_FILE, "w"), indent=0)
    if new:
        alert(new, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
