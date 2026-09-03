"""Agent memory — SQLite storage for applications, recruiters, patterns, audit log."""
import hashlib, json, os, re, sqlite3, time
from pathlib import Path
from urllib.parse import urlparse

SCHEMA_PATH = Path(__file__).parent.parent / "data" / "schema.sql"

# Tracking / cache-busting query params that make the SAME job look like a NEW url.
# Stripping these lets dedup recognize a re-scraped job as already-applied.
_TRACKING_PREFIXES = ("utm_", "gh_", "gclid", "fbclid", "ref", "source", "src",
                       "trk", "trackingid", "recommend", "eblid", "sponsored")

# --- Title normalization (so reworded reposts of the SAME role dedup) ---
# Seniority abbreviations -> canonical word (spell out, per ATS best practice)
_TITLE_SYNONYMS = {
    r"\bsr\.?\b": "senior",
    r"\bjr\.?\b": "junior",
    r"\bmid[- ]?level\b": "mid",
    r"\bback[- ]?end\b": "backend",
    r"\bfront[- ]?end\b": "frontend",
    r"\bfull[- ]?stack\b": "fullstack",
    r"\bsoftware development engineer\b": "software engineer",
    r"\bsde\b": "software engineer",
    r"\bswe\b": "software engineer",
    r"\bdev\b": "developer",
    r"\beng\.?\b": "engineer",
    r"\bengr\.?\b": "engineer",
    r"\bapp\b": "application",
    r"\bqa\b": "quality",
}


def normalize_title(title: str) -> str:
    """Canonicalize a job title so reworded variants of the SAME role match.

    Examples (all map to the same key):
      "Sr. Java Developer"            -> "java senior developer"* (sorted core)
      "Senior Java Developer (Remote)"
      "Java Developer - W2 ONLY - USC/GC - 100% REMOTE"
      "Back End Developer / Engineer II- #26-21402"

    Strategy (grounded in real scraped titles + ATS normalization best practice):
      1. lowercase
      2. cut everything after the first separator ( -, |, /, ( ) — these carry
         location / rate / ticket-number / "W2 ONLY" noise, not the role
      3. drop parenthetical / bracketed chunks and ticket numbers (#26-21402)
      4. expand seniority + role abbreviations (sr->senior, eng->engineer...)
      5. drop pure level markers (i, ii, iii, 1, 2, 3) and filler stopwords
      6. keep only alphanumerics, collapse whitespace, sort remaining tokens so
         word order ("Java Backend" == "Backend Java") does not matter

    Safe to call on anything; returns "" for empty input.
    """
    if not title:
        return ""
    t = title.lower().strip()

    # 2. Keep only the part before the first noisy separator.
    #    Only spaced separators — " / " is noise ("Java Dev / W2") but a bare
    #    slash ("AWS/Java") is part of the role, so it is NOT a split point here.
    for sep in (" - ", " | ", " – ", " / "):
        if sep in t:
            t = t.split(sep)[0]
    # Turn any remaining bare slashes into spaces (AWS/Java -> AWS Java)
    t = t.replace("/", " ")

    # 3. Remove parenthetical / bracketed noise and ticket numbers
    t = re.sub(r"\([^)]*\)", " ", t)
    t = re.sub(r"\[[^\]]*\]", " ", t)
    t = re.sub(r"#\S+", " ", t)
    t = re.sub(r"\b\d{2,}[- ]?\d*\b", " ", t)  # ticket / req numbers

    # 4. Expand abbreviations
    for pat, repl in _TITLE_SYNONYMS.items():
        t = re.sub(pat, repl, t)

    # 5. Strip level markers + filler
    _STOP = {"i", "ii", "iii", "iv", "1", "2", "3", "4",
             "the", "a", "an", "of", "for", "with", "and", "&",
             "remote", "hybrid", "onsite", "contract", "w2", "c2c",
             "usc", "gc", "only", "role", "position", "immediate"}
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    tokens = [w for w in t.split() if w and w not in _STOP]

    # 6. Sort tokens so word order does not create false uniqueness
    return " ".join(sorted(tokens))


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
    return f"{(company or '').strip().lower()}|{normalize_title(title)}"


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
    # DB-LEVEL LOCK for dedup (Bobur's idea): an atomic claim table so that even if
    # two runs (local + CI) execute concurrently, only ONE can claim a given
    # company+normalized-title and apply — the other's INSERT OR IGNORE is a no-op.
    # UNIQUE(claim_key) makes the claim atomic at the SQLite level (no race window).
    db.execute(
        """CREATE TABLE IF NOT EXISTS job_claims (
               claim_key TEXT UNIQUE NOT NULL,
               company   TEXT,
               title     TEXT,
               status    TEXT DEFAULT 'claimed',
               claimed_at TEXT DEFAULT (datetime('now'))
           )"""
    )
    db.commit()
    _purge_poisoned_answers(db)


def _claim_key(company: str, title: str) -> str:
    """Normalized company+title key for atomic dedup (matches greenhouse _gh_key intent
    but centralized in the DB layer). Empty if either part missing. Strips location /
    work-type qualifiers (us/usa/remote/w2/c2c/contract/onsite/hybrid) so reposts of the
    SAME role with those suffixes collapse to one key."""
    c = " ".join((company or "").lower().split())
    t = normalize_title(title or "")
    # drop trailing location/work-type noise that normalize_title keeps
    t = re.sub(r"\b(us|usa|remote|onsite|on-site|hybrid|w2|c2c|contract|contractor|"
               r"1099|fulltime|full-time|parttime|part-time)\b", " ", t)
    t = " ".join(t.split())
    return f"{c}|{t}" if c and t else ""


def claim_job(db: sqlite3.Connection, company: str, title: str) -> bool:
    """Atomically CLAIM a job (company+title) before applying. Returns True if THIS
    run won the claim (safe to apply) or already applied by us; False if another
    run/attempt already claimed it (skip — prevents concurrent double-apply).

    Uses INSERT OR IGNORE on a UNIQUE claim_key: the DB serializes the insert, so
    exactly one caller succeeds even under concurrency. If the key is unclaimable
    (missing company/title), returns True (fall back to the other dedup layers)."""
    key = _claim_key(company, title)
    if not key:
        return True
    try:
        cur = db.execute(
            "INSERT OR IGNORE INTO job_claims (claim_key, company, title) VALUES (?, ?, ?)",
            (key, company, title),
        )
        db.commit()
        # rowcount == 1 → we inserted (won the claim). 0 → row already existed (claimed).
        return cur.rowcount == 1
    except Exception:
        return True   # never block applying on a claim error; other dedup layers still apply


def release_claim(db: sqlite3.Connection, company: str, title: str) -> None:
    """Release a claim if the apply did NOT actually go through (so a later run can
    retry). Only call on a genuine failure, not on success."""
    key = _claim_key(company, title)
    if not key:
        return
    try:
        db.execute("DELETE FROM job_claims WHERE claim_key=? AND status='claimed'", (key,))
        db.commit()
    except Exception:
        pass


def _purge_poisoned_answers(db: sqlite3.Connection) -> None:
    """Self-heal wrong memory so a cached/persistent DB (CI or local) can't keep
    serving a bad answer even after the code is fixed.

    The 2026-09-02 bug saved the salary number ("75") as the answer to consent /
    attestation questions (the bare-substring "rate" false-matched "sepaRATEly" /
    "incorpoRATEd"). Memory is checked before the profile rules, so a poisoned row
    would defeat the code fix. Delete any consent/agreement question whose saved
    answer is a bare number — the fixed profile rule will re-answer it correctly.
    """
    try:
        rows = db.execute(
            "SELECT question_hash, question_text, approved_answer FROM approved_answers"
        ).fetchall()
    except Exception:
        return  # table not present yet
    consent_markers = (
        "i consent", "consent to the processing", "processing of my personal",
        "by sending us your application", "you confirm that you have read",
        "read and understood", "terms and conditions", "privacy policy",
        "privacy notice", "data protection", "answers will be shared",
    )
    bad_hashes = []
    for r in rows:
        ans = str(r["approved_answer"]).strip()
        q = (r["question_text"] or "").lower()
        # A bare number can never be the right answer to a consent/agreement radio.
        if ans.isdigit() and any(m in q for m in consent_markers):
            bad_hashes.append(r["question_hash"])
    for h in bad_hashes:
        db.execute("DELETE FROM approved_answers WHERE question_hash=?", (h,))
    if bad_hashes:
        db.commit()
        print(f"  🧹 memory self-heal: purged {len(bad_hashes)} poisoned consent answer(s)")


# --- Applications ---

def upsert_application(db: sqlite3.Connection, **kw) -> int:
    # Normalize the URL so the same job (with different tracking params) maps
    # to the same row. The UNIQUE(job_url) constraint then dedups automatically.
    if kw.get("job_url"):
        kw["job_url"] = normalize_job_url(kw["job_url"])
    # DYNAMIC guard: auto-fill any NOT NULL column that the caller didn't provide,
    # so a missing field (company / job_title / etc.) never aborts the record of a
    # REAL submit. Reads the live schema — works for any current/future NOT NULL col.
    try:
        for _cid, _name, _type, _notnull, _dflt, _pk in db.execute(
                "PRAGMA table_info(applications)").fetchall():
            if _notnull and not _pk and _dflt is None and _name not in kw:
                kw[_name] = "unknown" if "TEXT" in (_type or "").upper() else 0
    except Exception:
        pass
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

    # Fallback: same role at same company already applied under a different URL.
    # Compare NORMALIZED titles so reworded reposts match, e.g.
    #   "Sr. Java Developer" == "Senior Java Developer (Remote)" == "Java Developer - W2"
    if company and title:
        want = normalize_title(title)
        if want:
            rows = db.execute(
                "SELECT job_title, status FROM applications "
                "WHERE lower(trim(company))=? AND status IN "
                "('applied','submitted','dry_run','applied_via_email')",
                ((company or "").strip().lower(),),
            ).fetchall()
            for r in rows:
                if normalize_title(r[0]) == want:
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
