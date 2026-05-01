CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    job_title TEXT NOT NULL,
    job_url TEXT UNIQUE NOT NULL,
    ats_type TEXT,
    match_score REAL,
    ghost_score REAL,
    status TEXT DEFAULT 'found',
    applied_at TEXT,
    status_updated_at TEXT,
    days_to_response INTEGER,
    resume_version TEXT,
    cover_letter TEXT,
    source TEXT,
    rate TEXT,
    location TEXT,
    remote BOOLEAN,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS recruiters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    email TEXT UNIQUE NOT NULL,
    company TEXT,
    total_outreach INTEGER DEFAULT 0,
    total_responses INTEGER DEFAULT 0,
    ghosted_count INTEGER DEFAULT 0,
    quality_score REAL DEFAULT 0.5,
    last_contacted TEXT,
    last_responded TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ats_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ats_type TEXT NOT NULL,
    domain TEXT,
    total_steps INTEGER,
    field_selectors TEXT,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    version_hash TEXT,
    last_verified TEXT,
    UNIQUE(ats_type, domain)
);

CREATE TABLE IF NOT EXISTS approved_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_hash TEXT UNIQUE NOT NULL,
    question_text TEXT NOT NULL,
    approved_answer TEXT NOT NULL,
    source TEXT DEFAULT 'seed',
    confidence REAL DEFAULT 1.0,
    times_used INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT DEFAULT (datetime('now')),
    action TEXT NOT NULL,
    details TEXT,
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS email_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    times_sent INTEGER DEFAULT 0,
    times_replied INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS session_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT DEFAULT (date('now')),
    jobs_found INTEGER DEFAULT 0,
    jobs_filtered INTEGER DEFAULT 0,
    applications_sent INTEGER DEFAULT 0,
    emails_sent INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    duration_seconds REAL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS ghost_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_url TEXT NOT NULL,
    signal_name TEXT NOT NULL,
    signal_value REAL NOT NULL,
    weight REAL DEFAULT 1.0,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(job_url, signal_name)
);

-- Seed approved answers
INSERT OR IGNORE INTO approved_answers (question_hash, question_text, approved_answer, source) VALUES
('25c08b670d143f0d', 'Are you authorized to work in the United States?', 'Yes', 'seed'),
('518a58ab3ad0bbc1', 'Will you now or in the future require sponsorship?', 'No', 'seed'),
('3714a5bcb650c86d', 'What is your desired employment type?', 'Contract / C2C (Corp-to-Corp)', 'seed'),
('6a5f04bbfd4851c2', 'What are your salary expectations?', '$55-90/hr C2C depending on scope and duration', 'seed'),
('ea457083fb6c3684', 'How did you hear about this position?', 'Online Job Board', 'seed'),
('e9f89f5154750592', 'Are you willing to relocate?', 'Remote preferred; open to discussion', 'seed'),
('96c7c702ebe95952', 'When can you start?', 'Available immediately', 'seed'),
('cc90f1913b83d255', 'Gender', 'Decline to self-identify', 'seed'),
('6f93813600a3ff7a', 'Race/Ethnicity', 'Decline to self-identify', 'seed'),
('8124510ab7f9c8be', 'Veteran status', 'I am not a veteran', 'seed'),
('662f3d48a66f17a2', 'Disability status', 'I do not wish to answer', 'seed'),
('1b01cd435f782f90', 'Do you consent to a background check?', 'Yes', 'seed');

-- Seed email templates
INSERT OR IGNORE INTO email_templates (name, subject, body) VALUES
('initial_outreach',
 'Java Backend Developer — C2C Available Immediately',
 'Hi {recruiter_name},

I saw your posting for {job_title} and wanted to reach out directly.

I''m a Senior Java Backend Developer with 10+ years of experience in Spring Boot, Kafka, Kubernetes, AWS, MongoDB, and Cassandra. Green Card holder — no sponsorship needed.

My C2C rate range is $55-90/hr depending on scope.

CV: https://drive.google.com/drive/folders/1sJRyHCTC2Xend6VWn6hM07VufWQdw_qV

Happy to discuss further.

Best,
Bob Rikh
347-268-5917'),
('follow_up',
 'Re: Java Backend Developer — Following Up',
 'Hi {recruiter_name},

Just following up on my previous email regarding the {job_title} position. I''m still available and very interested.

Would love to schedule a quick call at your convenience.

Best,
Bob Rikh');
