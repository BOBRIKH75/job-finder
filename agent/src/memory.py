"""Agent memory — SQLite storage for applications, recruiters, patterns, audit log."""
import hashlib, json, os, sqlite3, time
from pathlib import Path
from urllib.parse import urlparse

SCHEMA_PATH = Path(__file__).parent.parent / "data" / "schema.sql"

# Tracking / cache-busting query params that make the SAME job look like a NEW url.
# Stripping these lets dedup recognize a re-scraped job as already-applied.
_TRACKING_PREFIXES = ("utm_", "gh_", "gclid", "fbclid", "ref", "source", "src",
                       "trk", "trackingid", "recommend", "eblid", "sponsored")


def normalize_job_url(job_url: str) -> str:
    """Normalize a job URL so the SAME job maps to the SAME key across runs.

    - Lowercases host + path
    - Drops the query string (tracking params) and fragment
    - Collapses known host prefixes (job-boards.greenhouse.io -> boards.greenhouse.io)
    - Strips www. and trailing slash

    Falls back to the raw (lowercased, trimmed) url if parsing fails, so it is
    always safe to call.
    """
    if not job_url:
        return ""
    try:
        p = urlparse(job_url.strip())
        # No scheme (bare string) -> just normalize the raw text
        if not p.netloc:
            return job_url.strip().rstrip("/").lower()
        host = p.netloc.lower()
        host = host.replace("job-boards.greenhouse.io", "boards.greenhouse.io")
        if host.startswith("www."):
            host = host[4:]
        path = p.path.rstrip("/").lower()
        return f"{host}{path}"
    except Exception:
        return job_url.strip().rstrip("/").lower()


def _role_key(company: str, title: str) -> str:
    """Stable key for the same role at the same company (URL-independent)."""
    return f"{(company or '').strip().lower()}|{(title or '').strip().lower()}"


def get_db(db_path: str = "data/agent_memory.db") -> sqlite3.Connection:
    if db_path == ":memory:":
        db = sqlite3.connect(":memory:")
    else:
        full = Path(__file__).parent.parent / db_path
        full.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(full))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db(db: sqlite3.Connection) -> None:
    schema = SCHEMA_PATH.read_text()
    db.executescript(schema)
    db.commit()


# --- Applications ---

def upsert_application(db: sqlite3.Connection, **kw) -> int:
    # Normalize the URL so the same job (with different tracking params) maps
    # to the same row. The UNIQUE(job_url) constraint then dedups automatically.
    if kw.get("job_url"):
        kw["job_url"] = normalize_job_url(kw["job_url"])
    cols = ", ".join(kw.keys())
    placeholders = ", ".join(["?"] * len(kw))
    updates = ", ".join(f"{k}=excluded.{k}" for k in kw if k != "job_url")
    sql = f"INSERT INTO applications ({cols}) VALUES ({placeholders}) ON CONFLICT(job_url) DO UPDATE SET {updates}"
    cur = db.execute(sql, list(kw.values()))
    db.commit()
    return cur.lastrowid


def get_applications(db: sqlite3.Connection, status: str = None, limit: int = 50) -> list[dict]:
    sql = "SELECT * FROM applications"
    params = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in db.execute(sql, params).fetchall()]


def update_application_status(db: sqlite3.Connection, job_url: str, status: str) -> None:
    db.execute(
        "UPDATE applications SET status=?, status_updated_at=datetime('now') WHERE job_url=?",
        (status, normalize_job_url(job_url)),
    )
    db.commit()


def application_exists(db: sqlite3.Connection, job_url: str,
                       company: str = None, title: str = None) -> bool:
    """True if this job was already applied/submitted (so we should skip it).

    Matches in two ways:
      1. Normalized URL (drops tracking params so re-scraped jobs are recognized)
      2. company + title fallback (same role, genuinely different URL)

    `company`/`title` are optional and backward compatible — old callers that
    pass only the url keep working exactly as before (just with URL normalized).
    """
    _APPLIED = ("applied", "submitted", "dry_run", "applied_via_email")

    row = db.execute(
        "SELECT status FROM applications WHERE job_url=?",
        (normalize_job_url(job_url),),
    ).fetchone()
    if row is not None and row[0] in _APPLIED:
        return True

    # Fallback: same role at same company already applied under a different URL
    if company and title:
        row = db.execute(
            "SELECT status FROM applications "
            "WHERE lower(trim(company))=? AND lower(trim(job_title))=?",
            ((company or "").strip().lower(), (title or "").strip().lower()),
        ).fetchone()
        if row is not None and row[0] in _APPLIED:
            return True

    return False


# --- Recruiters ---

def upsert_recruiter(db: sqlite3.Connection, email: str, **kw) -> int:
    kw["email"] = email
    cols = ", ".join(kw.keys())
    placeholders = ", ".join(["?"] * len(kw))
    updates = ", ".join(f"{k}=excluded.{k}" for k in kw if k != "email")
    sql = f"INSERT INTO recruiters ({cols}) VALUES ({placeholders}) ON CONFLICT(email) DO UPDATE SET {updates}"
    cur = db.execute(sql, list(kw.values()))
    db.commit()
    return cur.lastrowid


def get_recruiter(db: sqlite3.Connection, email: str) -> dict | None:
    row = db.execute("SELECT * FROM recruiters WHERE email=?", (email,)).fetchone()
    return dict(row) if row else None


# --- Approved Answers ---

def get_approved_answer(db: sqlite3.Connection, question: str) -> str | None:
    h = hashlib.md5(question.lower().strip().encode()).hexdigest()[:16]
    row = db.execute("SELECT approved_answer FROM approved_answers WHERE question_hash=?", (h,)).fetchone()
    if row:
        db.execute("UPDATE approved_answers SET times_used=times_used+1 WHERE question_hash=?", (h,))
        db.commit()
        return row["approved_answer"]
    return None


def save_approved_answer(db: sqlite3.Connection, question: str, answer: str, source: str = "user") -> None:
    h = hashlib.md5(question.lower().strip().encode()).hexdigest()[:16]
    db.execute(
        "INSERT OR REPLACE INTO approved_answers (question_hash, question_text, approved_answer, source) VALUES (?,?,?,?)",
        (h, question, answer, source),
    )
    db.commit()


# --- Audit Log ---

def audit(db: sqlite3.Connection, action: str, details: dict = None) -> None:
    row = db.execute("SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    prev = row["entry_hash"] if row else "GENESIS"
    payload = json.dumps({"ts": time.time(), "action": action, "details": details or {}, "prev": prev}, sort_keys=True)
    entry_hash = hashlib.sha256(payload.encode()).hexdigest()
    db.execute(
        "INSERT INTO audit_log (action, details, prev_hash, entry_hash) VALUES (?,?,?,?)",
        (action, json.dumps(details), prev, entry_hash),
    )
    db.commit()


def verify_audit_chain(db: sqlite3.Connection) -> bool:
    rows = db.execute("SELECT prev_hash, entry_hash FROM audit_log ORDER BY id").fetchall()
    expected = "GENESIS"
    for r in rows:
        if r["prev_hash"] != expected:
            return False
        expected = r["entry_hash"]
    return True


# --- Stats ---

def get_stats(db: sqlite3.Connection) -> dict:
    stats = {}
    for status in ("found", "applied", "callback", "interview", "offer", "rejected", "ghosted"):
        row = db.execute("SELECT COUNT(*) as c FROM applications WHERE status=?", (status,)).fetchone()
        stats[status] = row["c"]
    stats["total"] = sum(stats.values())
    return stats
