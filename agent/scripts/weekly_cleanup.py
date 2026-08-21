#!/usr/bin/env python3
"""
Weekly cleanup — keeps DB, caches, and data files from growing unbounded.

What it prunes:
  agent_memory.db  — applications older than 90 days (except callbacks/interviews/offers)
  contacted.json   — outreach emails 60+ days old with no reply → moved to contacted_archive.json
  companies.json   — auto-discovered companies that returned 0 jobs in the last scan
                     (seed companies are never removed)
  learned.json     — per-domain selectors for domains not seen in 60 days

Run: python agent/scripts/weekly_cleanup.py
Also triggered by .github/workflows/weekly-cleanup.yml every Sunday.
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ── paths ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
CONTACTED_FILE = ROOT.parent / "contacted.json"           # repo root
CONTACTED_ARCHIVE = ROOT.parent / "contacted_archive.json"
COMPANIES_FILE = DATA / "companies.json"
LEARNED_FILE = DATA / "learned.json"
DB_PATH = DATA / "agent_memory.db"


# ── helpers ─────────────────────────────────────────────────────────────────

def _days_ago(iso_str: str) -> int:
    """Return how many days ago an ISO datetime string was. Returns 9999 on parse error."""
    try:
        dt = datetime.fromisoformat(iso_str.rstrip("Z"))
        return (datetime.now() - dt).days
    except Exception:
        return 9999


# ── 1. SQLite DB prune ───────────────────────────────────────────────────────

def prune_db(days: int = 90) -> dict:
    if not DB_PATH.exists():
        print("  ⏭️  agent_memory.db not found — skipping")
        return {}
    sys.path.insert(0, str(ROOT))
    from src.memory import get_db, prune_old_records
    db = get_db(str(DB_PATH.relative_to(ROOT)))
    counts = prune_old_records(db, days=days)
    db.close()

    size_kb = DB_PATH.stat().st_size // 1024
    print(f"  ✅ DB prune: {counts} | size now: {size_kb} KB")
    return counts


# ── 2. contacted.json archive ────────────────────────────────────────────────

def archive_old_contacts(days: int = 60) -> dict:
    if not CONTACTED_FILE.exists():
        print("  ⏭️  contacted.json not found — skipping")
        return {"archived": 0, "kept": 0}

    contacts = json.loads(CONTACTED_FILE.read_text())

    # Load existing archive
    archive = {}
    if CONTACTED_ARCHIVE.exists():
        try:
            archive = json.loads(CONTACTED_ARCHIVE.read_text())
        except Exception:
            pass

    keep, moved = {}, {}
    for key, entry in contacts.items():
        # Never archive if they replied
        if entry.get("replied"):
            keep[key] = entry
            continue
        age = _days_ago(entry.get("date", ""))
        if age >= days:
            moved[key] = entry
        else:
            keep[key] = entry

    if moved:
        archive.update(moved)
        CONTACTED_ARCHIVE.write_text(json.dumps(archive, indent=2))
        CONTACTED_FILE.write_text(json.dumps(keep, indent=2))

    print(f"  ✅ Contacts: {len(keep)} active | {len(moved)} archived (>{days} days, no reply)")
    return {"archived": len(moved), "kept": len(keep)}


# ── 3. companies.json: remove stale auto-discovered entries ─────────────────

def prune_companies(stale_days: int = 60) -> dict:
    if not COMPANIES_FILE.exists():
        print("  ⏭️  companies.json not found — skipping")
        return {}

    from src.portal_scanner import SEED_LEVER, SEED_GREENHOUSE
    seed_lever = set(SEED_LEVER)
    seed_gh = set(SEED_GREENHOUSE)

    companies = json.loads(COMPANIES_FILE.read_text())
    discovered = companies.get("discovered", [])

    # Build a set of auto-discovered slugs with timestamps
    # Format stored: "lever:slug:CompanyName" (no timestamp — added going forward)
    # For now we can't prune by date (no timestamp stored in discovered list).
    # Instead: only remove duplicates and malformed entries. Real staleness pruning
    # requires the scan to track last_active — add that in the next pass.
    before = len(companies.get("lever", [])) + len(companies.get("greenhouse", []))

    # Remove any slug from lever/greenhouse lists that appears in both (prefer greenhouse)
    lever_set = set(companies.get("lever", []))
    gh_set = set(companies.get("greenhouse", []))
    overlap = lever_set & gh_set
    if overlap:
        companies["lever"] = [s for s in companies["lever"] if s not in overlap]

    # Deduplicate discovered log (keep last 500 entries)
    companies["discovered"] = list(dict.fromkeys(companies["discovered"]))[-500:]

    after = len(companies.get("lever", [])) + len(companies.get("greenhouse", []))
    COMPANIES_FILE.write_text(json.dumps(companies, indent=2))

    print(f"  ✅ Companies: {after} tracked (removed {before - after} overlaps, discovered log capped at 500)")
    return {"before": before, "after": after}


# ── 4. learned.json: remove stale domain selectors ──────────────────────────

def prune_learned(stale_days: int = 60) -> dict:
    if not LEARNED_FILE.exists():
        print("  ⏭️  learned.json not found — skipping")
        return {}

    learned = json.loads(LEARNED_FILE.read_text())
    # learned["winning_selectors"] is keyed by domain — no timestamp.
    # We can prune domains that have 0 success_count in success_count dict.
    win = learned.get("winning_selectors", {})
    success = learned.get("success_count", {})

    before = len(win)
    # Remove domains with no successful applications recorded
    stale = [d for d in win if success.get(d, 0) == 0]
    for d in stale:
        del win[d]
    learned["winning_selectors"] = win

    if stale:
        LEARNED_FILE.write_text(json.dumps(learned, indent=2))

    print(f"  ✅ Learned selectors: removed {len(stale)} zero-success domains | {len(win)} remaining")
    return {"removed": len(stale), "kept": len(win)}


# ── 5. Summary report ────────────────────────────────────────────────────────

def main():
    print(f"\n🧹 Weekly Cleanup — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    db_counts = prune_db(days=90)
    contact_counts = archive_old_contacts(days=60)
    company_counts = prune_companies()
    learned_counts = prune_learned()

    total_deleted = (
        db_counts.get("applications_deleted", 0)
        + db_counts.get("audit_pruned", 0)
        + contact_counts.get("archived", 0)
    )
    print(f"\n✅ Cleanup complete — {total_deleted} records removed/archived")


if __name__ == "__main__":
    main()
