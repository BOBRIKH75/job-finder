"""Self-evolving learning engine — grows smarter every run.

Stores everything the agent learns in SQLite (persisted via GitHub Actions cache).
Each run builds on the previous run's knowledge.

What it learns:
- Which selectors work for which domains (never re-discover)
- Which field formats each site expects (phone, date, salary)
- Which questions each site asks and the correct answers
- Which sites have CAPTCHAs (skip them next time)
- Which strategies work best per ATS type
- Error patterns and their fixes
- Success rate per domain (prioritize high-success sites)
"""
import json, hashlib
from datetime import datetime


def learn_selector(db, domain: str, selector: str, profile_key: str, worked: bool):
    """Remember which selector maps to which profile field for a domain."""
    db.execute("""
        INSERT INTO ats_patterns (ats_type, domain, field_selectors, success_count, failure_count, last_verified)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(ats_type, domain) DO UPDATE SET
            field_selectors = json_set(COALESCE(field_selectors, '{}'), '$.' || ?, ?),
            success_count = success_count + ?,
            failure_count = failure_count + ?,
            last_verified = ?
    """, (
        "learned", domain,
        json.dumps({selector: profile_key}),
        1 if worked else 0, 0 if worked else 1, datetime.now().isoformat(),
        selector, profile_key,
        1 if worked else 0, 0 if worked else 1, datetime.now().isoformat(),
    ))
    db.commit()


def get_learned_selectors(db, domain: str) -> dict:
    """Get all learned selectors for a domain. Returns {selector: profile_key}."""
    row = db.execute(
        "SELECT field_selectors FROM ats_patterns WHERE domain = ? ORDER BY success_count DESC LIMIT 1",
        (domain,)
    ).fetchone()
    if row and row["field_selectors"]:
        try:
            return json.loads(row["field_selectors"])
        except Exception:
            pass
    return {}


def learn_answer(db, question: str, answer: str, source: str = "learned"):
    """Save a new Q&A pair so the agent never has to figure it out again."""
    h = hashlib.md5(question.lower().strip().encode()).hexdigest()[:16]
    db.execute("""
        INSERT OR REPLACE INTO approved_answers (question_hash, question_text, approved_answer, source, confidence)
        VALUES (?, ?, ?, ?, 0.9)
    """, (h, question, answer, source))
    db.commit()


def learn_format(db, domain: str, field_name: str, format_used: str):
    """Remember what format a site expects for a field (e.g., phone format)."""
    key = f"format:{domain}:{field_name}"
    h = hashlib.md5(key.encode()).hexdigest()[:16]
    db.execute("""
        INSERT OR REPLACE INTO approved_answers (question_hash, question_text, approved_answer, source)
        VALUES (?, ?, ?, 'format')
    """, (h, key, format_used))
    db.commit()


def get_learned_format(db, domain: str, field_name: str) -> str | None:
    """Get the format a site expects for a field."""
    key = f"format:{domain}:{field_name}"
    h = hashlib.md5(key.encode()).hexdigest()[:16]
    row = db.execute("SELECT approved_answer FROM approved_answers WHERE question_hash = ?", (h,)).fetchone()
    return row["approved_answer"] if row else None


def learn_blocked_site(db, domain: str, reason: str):
    """Mark a site as blocked (CAPTCHA, login required, etc.) so we skip it next time."""
    db.execute("""
        INSERT OR REPLACE INTO ats_patterns (ats_type, domain, field_selectors, version_hash, last_verified)
        VALUES ('blocked', ?, ?, ?, ?)
    """, (domain, json.dumps({"reason": reason}), reason, datetime.now().isoformat()))
    db.commit()


def is_blocked_site(db, domain: str) -> str | None:
    """Check if a site is blocked. Returns reason or None."""
    # NEVER block multi-tenant ATS domains (they host many companies)
    NEVER_BLOCK = {"jobs.lever.co", "job-boards.greenhouse.io", "boards.greenhouse.io",
                   "jobs.ashbyhq.com", "apply.workable.com", "boards.eu.greenhouse.io"}
    if domain in NEVER_BLOCK:
        return None
    row = db.execute(
        "SELECT version_hash FROM ats_patterns WHERE ats_type = 'blocked' AND domain = ?", (domain,)
    ).fetchone()
    return row["version_hash"] if row else None


def learn_from_success(db, domain: str, job_url: str, selectors_used: list, fields_filled: int):
    """Record a successful application — everything that worked."""
    from src.memory import audit
    audit(db, "LEARN_SUCCESS", {
        "domain": domain, "url": job_url,
        "selectors": selectors_used[:20],
        "fields_filled": fields_filled,
        "timestamp": datetime.now().isoformat(),
    })


def learn_from_failure(db, domain: str, job_url: str, errors: list, attempt: int):
    """Record a failed application — what went wrong."""
    from src.memory import audit
    audit(db, "LEARN_FAILURE", {
        "domain": domain, "url": job_url,
        "errors": errors[:10],
        "attempt": attempt,
        "timestamp": datetime.now().isoformat(),
    })


def get_success_rate(db, domain: str) -> float:
    """Get success rate for a domain (0.0 to 1.0)."""
    row = db.execute("""
        SELECT 
            SUM(CASE WHEN action = 'LEARN_SUCCESS' AND json_extract(details, '$.domain') = ? THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN action IN ('LEARN_SUCCESS', 'LEARN_FAILURE') AND json_extract(details, '$.domain') = ? THEN 1 ELSE 0 END) as total
        FROM audit_log
    """, (domain, domain)).fetchone()
    if row and row["total"] and row["total"] > 0:
        return row["wins"] / row["total"]
    return 0.5  # unknown = assume 50%


def get_learning_stats(db) -> dict:
    """Get overall learning statistics."""
    stats = {}
    # Learned selectors
    row = db.execute("SELECT COUNT(*) as c FROM ats_patterns WHERE ats_type = 'learned'").fetchone()
    stats["domains_learned"] = row["c"]
    # Blocked sites
    row = db.execute("SELECT COUNT(*) as c FROM ats_patterns WHERE ats_type = 'blocked'").fetchone()
    stats["sites_blocked"] = row["c"]
    # Learned answers
    row = db.execute("SELECT COUNT(*) as c FROM approved_answers WHERE source IN ('learned', 'ai', 'format')").fetchone()
    stats["answers_learned"] = row["c"]
    # Total successes
    row = db.execute("SELECT COUNT(*) as c FROM audit_log WHERE action = 'LEARN_SUCCESS'").fetchone()
    stats["total_successes"] = row["c"]
    # Total failures
    row = db.execute("SELECT COUNT(*) as c FROM audit_log WHERE action = 'LEARN_FAILURE'").fetchone()
    stats["total_failures"] = row["c"]
    return stats


# ─── Stealth Tool Memory ────────────────────────────────────────────
# Remembers which stealth tool worked for which domain.
# Next run → tries the proven tool first → skips broken ones → faster + fewer failures.

STEALTH_MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS stealth_memory (
    domain TEXT NOT NULL,
    tool TEXT NOT NULL,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    last_success TEXT,
    last_failure TEXT,
    avg_time_ms REAL DEFAULT 0,
    UNIQUE(domain, tool)
);
"""


def ensure_stealth_memory_table(db):
    """Create stealth_memory table if it doesn't exist."""
    db.executescript(STEALTH_MEMORY_SCHEMA)


def learn_stealth_success(db, domain: str, tool: str, elapsed_ms: float):
    """Record that a stealth tool worked for a domain."""
    ensure_stealth_memory_table(db)
    db.execute("""
        INSERT INTO stealth_memory (domain, tool, success_count, last_success, avg_time_ms)
        VALUES (?, ?, 1, datetime('now'), ?)
        ON CONFLICT(domain, tool) DO UPDATE SET
            success_count = success_count + 1,
            last_success = datetime('now'),
            avg_time_ms = (avg_time_ms * success_count + ?) / (success_count + 1)
    """, (domain, tool, elapsed_ms, elapsed_ms))
    db.commit()


def learn_stealth_failure(db, domain: str, tool: str, error: str = ""):
    """Record that a stealth tool failed for a domain."""
    ensure_stealth_memory_table(db)
    db.execute("""
        INSERT INTO stealth_memory (domain, tool, failure_count, last_failure)
        VALUES (?, ?, 1, datetime('now'))
        ON CONFLICT(domain, tool) DO UPDATE SET
            failure_count = failure_count + 1,
            last_failure = datetime('now')
    """, (domain, tool))
    db.commit()


def get_best_tool_for_domain(db, domain: str) -> str | None:
    """Get the best stealth tool for a domain based on past success.
    
    Returns the tool name with highest success rate, or None if no data.
    Ignores tools that failed >3 times with 0 successes (proven broken).
    """
    ensure_stealth_memory_table(db)
    row = db.execute("""
        SELECT tool, success_count, failure_count,
               CAST(success_count AS REAL) / MAX(success_count + failure_count, 1) AS success_rate
        FROM stealth_memory
        WHERE domain = ?
          AND success_count > 0
        ORDER BY success_rate DESC, success_count DESC, avg_time_ms ASC
        LIMIT 1
    """, (domain,)).fetchone()
    if row:
        return row["tool"]
    return None


def get_tools_to_skip(db, domain: str, min_failures: int = 3) -> list[str]:
    """Get tools that consistently fail for a domain (skip them).
    
    A tool is skipped if it failed >=min_failures times with 0 successes.
    """
    ensure_stealth_memory_table(db)
    rows = db.execute("""
        SELECT tool FROM stealth_memory
        WHERE domain = ?
          AND failure_count >= ?
          AND success_count = 0
    """, (domain, min_failures)).fetchall()
    return [r["tool"] for r in rows]


def get_smart_tool_order(db, domain: str, default_chain: list[str]) -> list[str]:
    """Reorder the tool chain based on memory — smart first, skip broken.
    
    1. Best tool for this domain goes FIRST
    2. Tools that always fail for this domain are REMOVED
    3. Rest stays in default order
    
    Returns optimized tool name list.
    """
    best = get_best_tool_for_domain(db, domain)
    skip = get_tools_to_skip(db, domain)
    
    # Remove broken tools
    chain = [t for t in default_chain if t not in skip]
    
    # Move best to front
    if best and best in chain:
        chain.remove(best)
        chain.insert(0, best)
    
    return chain
