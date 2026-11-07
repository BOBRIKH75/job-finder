"""Gmail reconciliation for Greenhouse/ATS: which submits are REALLY confirmed by email.

A confirmation email ("Thank you for applying to <Company>", "Your application to <Company>",
"We received your application ...") is ground truth that an application landed. This module
reads those subjects (headers only, never bodies), stores them in
agent/data/greenhouse_confirmed.json and reports how many of today's recorded submits are
confirmed. Never prints addresses or bodies.
"""
import email
import imaplib
import json
import os
import re
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parsedate_to_datetime

CONFIRMED_FILE = os.path.join("agent", "data", "greenhouse_confirmed.json")

_CONFIRM_PATTERNS = (
    re.compile(r"thank(?:s| you) for (?:applying|your application|your interest)(?: to| at| with|,)?\s*(.*)", re.I),
    re.compile(r"your application (?:to|for|at|with)\s+(.*)", re.I),
    re.compile(r"we(?:'ve| have)? received your application(?: (?:to|for|at|with))?\s*(.*)", re.I),
    re.compile(r"application (?:received|submitted)[:\-–]?\s*(.*)", re.I),
)
_NOT_CONFIRM = re.compile(r"security code|verify|verification|unfortunately|not moving|update on your|"
                          r"interview|invitation|job alert|reset", re.I)


def _decode(s):
    out = ""
    for part, enc in decode_header(s or ""):
        out += part.decode(enc or "utf-8", "ignore") if isinstance(part, bytes) else part
    return out


def parse_confirmation_subject(subject):
    """Return the company/job text from a confirmation subject, or None if not a confirmation."""
    subj = (subject or "").strip()
    if not subj or _NOT_CONFIRM.search(subj):
        return None
    for pat in _CONFIRM_PATTERNS:
        m = pat.search(subj)
        if m:
            rest = re.sub(r"[!.\s]+$", "", m.group(1) or "").strip()
            return rest or "(unknown)"
    return None


def load_confirmed(path=CONFIRMED_FILE):
    try:
        return json.load(open(path))
    except Exception:
        return []


def fetch_confirmations(days=2):
    """Scan Gmail headers for confirmation subjects in the last `days` days.
    Returns [{'what': str, 'subject': str, 'date': iso}]; [] if no credentials/IMAP error."""
    user, pw = os.environ.get("GMAIL_USER", ""), os.environ.get("GMAIL_APP_PASSWORD", "")
    if not user or not pw:
        return []
    out = []
    try:
        M = imaplib.IMAP4_SSL("imap.gmail.com")
        M.login(user, pw)
        M.select('"[Gmail]/All Mail"', readonly=True)
        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        for frm in ("greenhouse", "ashbyhq", "lever", "workable"):
            typ, data = M.search(None, f'(SINCE {since} FROM "{frm}")')
            for i in (data[0].split() if typ == "OK" and data and data[0] else []):
                t, md = M.fetch(i, "(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE)])")
                if t != "OK":
                    continue
                m = email.message_from_string(md[0][1].decode("utf-8", "ignore"))
                subj = _decode(m.get("Subject"))
                what = parse_confirmation_subject(subj)
                if what is None:
                    continue
                try:
                    when = parsedate_to_datetime(m.get("Date")).isoformat()
                except Exception:
                    when = ""
                out.append({"what": what[:80], "subject": subj[:120], "date": when})
        M.logout()
    except Exception as exc:
        print(f"  ⚠ gmail reconcile error: {str(exc)[:60]}")
    return out


def reconcile(days=2, path=CONFIRMED_FILE):
    """Fetch confirmations, merge into the tracked JSON, and return (new_count, total_in_window)."""
    found = fetch_confirmations(days)
    if not found:
        return 0, 0
    existing = load_confirmed(path)
    seen = {(e.get("subject"), e.get("date")) for e in existing}
    new = [f for f in found if (f["subject"], f["date"]) not in seen]
    merged = (existing + new)[-1000:]
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump(merged, open(path, "w"), indent=0)
    except Exception:
        pass
    return len(new), len(found)


def confirmed_for(company, confirmations):
    """True if any confirmation mentions the company (loose alnum prefix match)."""
    key = re.sub(r"[^a-z0-9]", "", (company or "").lower())[:6]
    if not key:
        return False
    return any(key in re.sub(r"[^a-z0-9]", "", (c.get("what", "") + c.get("subject", "")).lower())
               for c in confirmations)
