#!/usr/bin/env python3
"""
Daily summary email — runs at 9 PM MT every day.
Pulls real numbers from agent_memory.db + contacted.json + gmail reply tracker.
Sends via Resend to bobrikh75@gmail.com.
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
DB_PATH = DATA / "agent_memory.db"
CONTACTED_FILE = ROOT.parent / "contacted.json"
COMPANIES_FILE = DATA / "companies.json"

RESEND_KEY = os.environ.get("RESEND_KEY", "")
GMAIL_USER = os.environ.get("GMAIL_USER", "bobrikh75@gmail.com")


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection | None:
    if not DB_PATH.exists():
        return None
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db


def today_stats(db: sqlite3.Connection) -> dict:
    today = date.today().isoformat()

    # Total applied today
    row = db.execute(
        "SELECT COUNT(*) as c FROM applications WHERE DATE(created_at)=? AND status IN ('applied','submitted','dry_run')",
        (today,),
    ).fetchone()
    total_today = row["c"] if row else 0

    # By ATS platform
    rows = db.execute(
        "SELECT ats_type, COUNT(*) as c FROM applications "
        "WHERE DATE(created_at)=? AND status IN ('applied','submitted','dry_run') "
        "GROUP BY ats_type ORDER BY c DESC",
        (today,),
    ).fetchall()
    by_platform = {r["ats_type"] or "unknown": r["c"] for r in rows}

    # Applied in last 7 days (daily trend)
    trend = {}
    for i in range(7):
        d = (date.today() - timedelta(days=i)).isoformat()
        row = db.execute(
            "SELECT COUNT(*) as c FROM applications WHERE DATE(created_at)=? AND status IN ('applied','submitted','dry_run')",
            (d,),
        ).fetchone()
        trend[d] = row["c"] if row else 0

    # All-time counts by status
    all_rows = db.execute(
        "SELECT status, COUNT(*) as c FROM applications GROUP BY status"
    ).fetchall()
    all_time = {r["status"]: r["c"] for r in all_rows}

    # New companies discovered today
    companies_data = {}
    if COMPANIES_FILE.exists():
        companies_data = json.loads(COMPANIES_FILE.read_text())
    discovered_today = sum(
        1 for entry in companies_data.get("discovered", [])
        if today in entry
    )

    return {
        "total_today": total_today,
        "by_platform": by_platform,
        "trend": trend,
        "all_time": all_time,
        "discovered_today": discovered_today,
        "total_companies": len(companies_data.get("lever", [])) + len(companies_data.get("greenhouse", [])),
    }


def outreach_stats() -> dict:
    if not CONTACTED_FILE.exists():
        return {"total_contacted": 0, "replies": 0, "pending": 0}
    contacted = json.loads(CONTACTED_FILE.read_text())
    replies = sum(1 for v in contacted.values() if v.get("replied"))
    blacklisted = sum(1 for v in contacted.values() if v.get("blacklisted"))
    return {
        "total_contacted": len(contacted),
        "replies": replies,
        "pending": len(contacted) - replies - blacklisted,
        "blacklisted": blacklisted,
    }


def learned_stats() -> int:
    answers_file = DATA / "learned_answers.json"
    if not answers_file.exists():
        return 0
    return len(json.loads(answers_file.read_text()))


# ── Credential status ─────────────────────────────────────────────────────────

def cred_status() -> dict:
    state_file = DATA / "credential_state.json"
    if not state_file.exists():
        return {}
    return json.loads(state_file.read_text())


# ── Report builder ────────────────────────────────────────────────────────────

_PLATFORM_LABELS = {
    "lever":       "Lever",
    "greenhouse":  "Greenhouse API",
    "dice":        "Dice",
    "ziprecruiter":"ZipRecruiter",
    "linkedin":    "LinkedIn Easy Apply",
    "indeed":      "Indeed",
    "ashby":       "Ashby",
    "workable":    "Workable",
    "unknown":     "Other (browser)",
    None:          "Other",
}


def build_report(stats: dict, outreach: dict, answers_count: int, creds: dict) -> tuple[str, str]:
    today_str = datetime.now().strftime("%b %d, %Y")
    day_of_week = datetime.now().strftime("%A")

    total = stats["total_today"]
    all_time_applied = sum(
        stats["all_time"].get(s, 0)
        for s in ("applied", "submitted", "dry_run")
    )
    callbacks = stats["all_time"].get("callback", 0)
    interviews = stats["all_time"].get("interview", 0)
    offers = stats["all_time"].get("offer", 0)

    # Platform breakdown lines
    platform_lines = []
    for ats, count in sorted(stats["by_platform"].items(), key=lambda x: -x[1]):
        label = _PLATFORM_LABELS.get(ats, ats or "Other")
        # Show credential status if bad
        cred_key = "LINKEDIN_COOKIES" if ats == "linkedin" else None
        cred_note = ""
        if cred_key and creds.get(cred_key, "ok") != "ok":
            cred_note = f" ⚠️ {creds[cred_key]}"
        platform_lines.append(f"    {label}: {count}{cred_note}")

    # 7-day trend
    trend_parts = []
    for d, c in sorted(stats["trend"].items()):
        day_label = datetime.fromisoformat(d).strftime("%a")
        trend_parts.append(f"{day_label}:{c}")
    trend_str = "  |  ".join(trend_parts)

    # Credential issues
    bad_creds = [f"{k}: {v}" for k, v in creds.items() if v != "ok"]
    cred_line = "  Credentials: all OK ✅" if not bad_creds else f"  ⚠️  Issues: {', '.join(bad_creds)}"

    subject = f"📊 Job Agent — {total} apps today ({day_of_week} {today_str})"

    body = f"""📊 Daily Report — {day_of_week}, {today_str}
{'═' * 40}

APPLICATIONS TODAY: {total}
{chr(10).join(platform_lines) if platform_lines else '    (no applications recorded)'}

OUTREACH EMAILS
  Total contacted: {outreach['total_contacted']}
  Replies: {outreach['replies']}
  Pending: {outreach['pending']}

DISCOVERY
  Companies in database: {stats['total_companies']}
  New companies today: {stats['discovered_today']}
  Learned form answers: {answers_count}

7-DAY TREND
  {trend_str}

ALL-TIME RESULTS
  Applied:    {all_time_applied:>5}
  Callbacks:  {callbacks:>5}
  Interviews: {interviews:>5}
  Offers:     {offers:>5}
  Reply rate: {(callbacks / all_time_applied * 100):.1f}% {"(too early to measure)" if all_time_applied < 50 else ""}

SYSTEM STATUS
{cred_line}

{'═' * 40}
Next run: tomorrow morning
"""
    return subject, body


# ── Send ──────────────────────────────────────────────────────────────────────

def send_report(subject: str, body: str) -> bool:
    if not RESEND_KEY:
        print("No RESEND_KEY — printing report only")
        print(body)
        return False

    import urllib.request
    payload = json.dumps({
        "from": "Job Agent <onboarding@resend.dev>",
        "to": [GMAIL_USER],
        "subject": subject,
        "text": body,
    }).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {RESEND_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=15)
        print(f"✅ Daily report sent to {GMAIL_USER}")
        return True
    except Exception as e:
        print(f"❌ Failed to send report: {e}")
        print(body)
        return False


def main():
    print(f"[{datetime.now().strftime('%H:%M')}] Building daily report...")

    db = get_db()
    if not db:
        print("⚠️  No database found — run the agent first to generate data")
        stats = {
            "total_today": 0, "by_platform": {}, "trend": {},
            "all_time": {}, "discovered_today": 0, "total_companies": 0,
        }
    else:
        stats = today_stats(db)
        db.close()

    outreach = outreach_stats()
    answers_count = learned_stats()
    creds = cred_status()

    subject, body = build_report(stats, outreach, answers_count, creds)
    print(body)
    send_report(subject, body)


if __name__ == "__main__":
    main()
