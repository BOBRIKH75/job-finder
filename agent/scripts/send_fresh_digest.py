#!/usr/bin/env python3
"""
Fresh Jobs Digest (NEW, additive) — emails Bob the NEW jobs found by the multi-source
discovery, with direct apply links, so he can manually apply to the ones the bot can't
auto-submit (RemoteOK/WWR/external). Via Gmail SMTP. Read-only on data files.

Only includes jobs first_seen in the last DIGEST_HOURS (default 24h) so it's not spammy.
Run: python scripts/send_fresh_digest.py
"""
import json, os, smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

DISC = Path(__file__).parent.parent / "data" / "discovered_jobs.json"
GMAIL_USER = os.environ.get("GMAIL_USER", "bobrikh75@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
DIGEST_HOURS = int(os.environ.get("DIGEST_HOURS", "24"))


def main():
    if not DISC.exists():
        print("no discovered_jobs.json")
        return
    jobs = json.loads(DISC.read_text())
    cutoff = datetime.utcnow() - timedelta(hours=DIGEST_HOURS)
    fresh = []
    for j in jobs:
        fs = j.get("first_seen", "")
        try:
            if fs and datetime.fromisoformat(fs.replace("Z", "")) >= cutoff:
                fresh.append(j)
        except Exception:
            continue
    if not fresh:
        print("no new jobs in window — no digest sent")
        return

    # group by source
    by_src = {}
    for j in fresh:
        by_src.setdefault(j.get("source", "other"), []).append(j)

    rows = []
    for src in sorted(by_src):
        rows.append(f"\n=== {src.upper()} ({len(by_src[src])}) ===")
        for j in by_src[src][:40]:
            loc = j.get("location", "")
            rows.append(f"• {j.get('title','')[:60]}  @ {j.get('company','')[:25]}  {('['+loc[:20]+']') if loc else ''}")
            rows.append(f"    {j.get('url','')}")

    body = (
        f"Hi Bob,\n\n{len(fresh)} NEW Java jobs found in the last {DIGEST_HOURS}h "
        f"across RemoteOK / We Work Remotely / ZipRecruiter / Google.\n"
        f"(Greenhouse/Lever ones are auto-applied; the rest below — apply directly.)\n"
        + "\n".join(rows) +
        "\n\n— Job Finder (multi-source discovery)\n"
    )

    if not GMAIL_APP_PASSWORD:
        print(f"[DRY RUN] would email {len(fresh)} new jobs")
        print(body[:500])
        return

    msg = MIMEMultipart()
    msg["From"] = f"Job Finder <{GMAIL_USER}>"
    msg["To"] = GMAIL_USER
    msg["Subject"] = f"🔎 {len(fresh)} new Java jobs today (RemoteOK/WWR/Zip/Google)"
    msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
            s.starttls()
            s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            s.send_message(msg)
        print(f"✅ digest emailed: {len(fresh)} new jobs")
    except Exception as e:
        print(f"❌ email failed: {str(e)[:80]}")


if __name__ == "__main__":
    main()
