#!/usr/bin/env python3
"""Harvest Gmail bounce notices into agent/data/do_not_contact.txt.

WHY (Nov 2026 audit): ~1/3 of weekly cold sends bounced and 198 of 306 bounced vendor
addresses were re-sent more than once, because nothing ever turned a bounce into a
suppression. Repeated bounces/blocks wreck Gmail sender reputation, which pushes REAL
recruiter mail (and calls) away. This closes the loop:

  bounce (mailer-daemon)  ->  permanent failure?  ->  do_not_contact.txt  (+ contacted.json bounced=True)

Permanent = address not found / 5.x.x / recipient blocked us. Temporary (4.x.x, mailbox full,
delayed) is ignored. A dead DOMAIN is suppressed as "@domain" so every guess at it stops.

Usage: python scripts/bounce_harvester.py [--days 30] [--dry-run]
Needs GMAIL_USER + GMAIL_APP_PASSWORD. Read-only on Gmail. Idempotent.
"""
import imaplib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
DNC = DATA / "do_not_contact.txt"
CONTACTED = Path(__file__).resolve().parent.parent.parent / "contacted.json"

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

RECIPIENT_RES = [
    re.compile(r"(?:wasn't delivered to|was not delivered to|delivered to)\s+<?([\w.+-]+@[\w.-]+\.[a-z]{2,})", re.I),
    re.compile(r"Your message to\s+<?([\w.+-]+@[\w.-]+\.[a-z]{2,})>?\s+has been blocked", re.I),
    re.compile(r"Final-Recipient:\s*rfc822;\s*<?([\w.+-]+@[\w.-]+\.[a-z]{2,})", re.I),
    re.compile(r"X-Failed-Recipients:\s*<?([\w.+-]+@[\w.-]+\.[a-z]{2,})", re.I),
]
PERMANENT_RE = re.compile(
    r"couldn't be found|could not be found|address not found|does not exist|no such user|"
    r"unknown user|user unknown|recipient address rejected|mailbox unavailable|"
    r"invalid recipient|has been blocked|message blocked|\b5\.\d\.\d\b|\b55\d\b", re.I)
TEMPORARY_RE = re.compile(r"\b4\.\d\.\d\b|mailbox (is )?full|over quota|temporar|try again later|delayed", re.I)
DOMAIN_DEAD_RE = re.compile(r"domain (name )?(not found|couldn't be found|does not exist)|DNS (Error|type)|"
                            r"no MX|Host or domain name not found|NXDOMAIN", re.I)


def parse_bounce(text: str):
    """Return (kind, address, domain_dead) where kind in {'permanent','temporary',None}."""
    addr = None
    for rx in RECIPIENT_RES:
        m = rx.search(text)
        if m:
            addr = m.group(1).lower()
            break
    if not addr:
        return None, None, False
    if TEMPORARY_RE.search(text) and not PERMANENT_RE.search(text):
        return "temporary", addr, False
    if PERMANENT_RE.search(text):
        return "permanent", addr, bool(DOMAIN_DEAD_RE.search(text))
    return None, addr, False


def load_dnc() -> list:
    return DNC.read_text().splitlines() if DNC.exists() else []


def main():
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 30
    dry = "--dry-run" in sys.argv
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("bounce_harvester: no Gmail credentials - skipping")
        return 0

    try:
        conn = imaplib.IMAP4_SSL("imap.gmail.com")
        conn.sock.settimeout(120)
        conn.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        conn.select('"[Gmail]/All Mail"', readonly=True)
        typ, data = conn.search(None, "X-GM-RAW", f'"from:(mailer-daemon OR postmaster) newer_than:{days}d"')
        ids = data[0].split() if typ == "OK" else []
    except Exception as exc:
        print(f"bounce_harvester: IMAP error ({type(exc).__name__}) - skipping, nothing changed")
        return 0

    own = GMAIL_USER.lower()
    perm, dead_domains, temp = set(), set(), 0
    for k in range(0, len(ids), 50):
        try:
            typ, parts = conn.fetch(b",".join(ids[k:k + 50]), "(BODY.PEEK[TEXT]<0.1500>)")
        except Exception:
            continue
        for part in parts:
            if not isinstance(part, tuple):
                continue
            kind, addr, dead = parse_bounce(part[1].decode("utf8", "ignore"))
            if not addr or addr == own:
                continue
            if kind == "permanent":
                perm.add(addr)
                if dead:
                    dead_domains.add("@" + addr.rpartition("@")[2])
            elif kind == "temporary":
                temp += 1
    try:
        conn.logout()
    except Exception:
        pass

    existing = {l.strip().lower() for l in load_dnc() if l.strip() and not l.startswith("#")}
    new = sorted((perm | dead_domains) - existing)
    print(f"bounce_harvester: {len(ids)} bounce msgs/{days}d | permanent addrs {len(perm)} | "
          f"dead domains {len(dead_domains)} | temporary ignored {temp} | NEW suppressions {len(new)}")
    if dry or not new:
        return 0

    DNC.parent.mkdir(parents=True, exist_ok=True)
    prefix = "" if (not DNC.exists() or DNC.read_text().endswith("\n")) else "\n"
    with DNC.open("a") as f:
        f.write(prefix)
        f.write(f"# auto-harvested bounces {datetime.utcnow():%Y-%m-%d} (bounce_harvester.py)\n")
        f.write("\n".join(new) + "\n")

    # Mark main-pipeline contacts so follow-ups/re-engagement never retry them.
    try:
        if CONTACTED.exists():
            c = json.loads(CONTACTED.read_text())
            changed = 0
            for v in c.values():
                em = (v.get("email") or "").lower()
                if (em in perm or "@" + em.rpartition("@")[2] in dead_domains) and not v.get("bounced"):
                    v["bounced"] = True
                    changed += 1
            if changed:
                CONTACTED.write_text(json.dumps(c, indent=2))
                print(f"bounce_harvester: marked {changed} contacted.json entries bounced")
    except Exception as exc:
        print(f"bounce_harvester: contacted.json update skipped ({type(exc).__name__})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
