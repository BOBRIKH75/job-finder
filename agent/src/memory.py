"""Agent memory — SQLite storage for applications, recruiters, patterns, audit log."""
import hashlib, json, os, sqlite3, time
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent.parent / "data" / "schema.sql"


def get_db(db_path: str = "data/agent_memory.db") -> sqlite3.Connection:
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
        (status, job_url),
    )
    db.commit()


def application_exists(db: sqlite3.Connection, job_url: str) -> bool:
    row = db.execute("SELECT 1 FROM applications WHERE job_url=?", (job_url,)).fetchone()
    return row is not None


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
