"""CV-relevance matcher — apply ONLY to jobs that fit Bob's CV.

Bob Rikh: Senior Java Back-End Developer. Java 17, Spring Boot, microservices,
Kafka, Kubernetes, AWS, REST/GraphQL, SQL/NoSQL. Remote-preferred, C2C/contract.

We do NOT want to burn submits (especially while rate-limited) on off-target roles
like frontend-only, .NET, salesforce, data-entry, sales, nursing, driver, etc.

Env overrides:
  CV_MATCH_OFF=1        -> disable filtering (apply to everything, old behavior)
  CV_MATCH_MIN=<int>    -> minimum score to apply (default 2)
"""
import os

# --- Core role signals: at least one MUST be present (this is a Java backend role) ---
CORE_MUST = (
    "java", "spring", "spring boot", "springboot", "backend", "back-end", "back end",
    "microservice", "microservices", "software engineer", "software developer",
    "full stack", "fullstack", "full-stack",
)

# --- Positive skills: each adds to the score (the more of Bob's stack, the better) ---
POSITIVE = (
    "java", "spring", "spring boot", "spring cloud", "spring mvc", "spring security",
    "microservice", "microservices", "kafka", "kubernetes", "docker", "aws",
    "rest", "restful", "api", "graphql", "postgresql", "mysql", "oracle", "mongodb",
    "cassandra", "redis", "hibernate", "jpa", "maven", "gradle", "junit", "mockito",
    "ci/cd", "jenkins", "gitlab", "devops", "distributed", "event-driven", "backend",
    "back-end", "j2ee", "jakarta", "reactive", "webflux", "grpc", "kafka streams",
)

# --- Remote / work-type bonus (Bob is remote + C2C) ---
REMOTE_BONUS = ("remote", "work from home", "wfh", "telecommute", "anywhere", "us remote")
C2C_BONUS = ("c2c", "corp to corp", "corp-to-corp", "contract", "contractor", "1099", "w2")

# --- Hard negatives: if the TITLE is clearly a different field, skip regardless ---
TITLE_NEGATIVES = (
    ".net", "c#", "dotnet", "php", "ruby on rails", "salesforce", "sap ", "workday",
    "frontend only", "front-end only", "ui/ux", "designer", "sales ", "account executive",
    "recruiter", "nurse", "nursing", "driver", "warehouse", "cashier", "data entry",
    "qa manual", "manual tester", "servicenow", "sharepoint", "cobol", "mainframe",
    "android developer", "ios developer", "mobile developer", "golang only", "python developer",
    "data scientist", "machine learning engineer", "devops engineer only", "network engineer",
    "business analyst", "project manager", "scrum master", "product manager",
)


def _norm(s):
    return (s or "").lower()


def score_job(title, description="", location=""):
    """Return (score, reasons). Higher = better fit. 0 or negative = skip."""
    t = _norm(title)
    d = _norm(description)
    loc = _norm(location)
    blob = f"{t} {d} {loc}"
    reasons = []

    # Hard negative in the TITLE -> immediate skip (wrong field entirely).
    for neg in TITLE_NEGATIVES:
        if neg in t:
            return (-100, [f"title negative: '{neg.strip()}'"])

    # Must look like a Java/backend role somewhere.
    if not any(k in blob for k in CORE_MUST):
        return (-10, ["no core Java/backend signal"])

    score = 0
    hits = [k for k in POSITIVE if k in blob]
    score += len(set(hits))
    if hits:
        reasons.append(f"skills:{len(set(hits))}")
    # Strong core boost if Java + Spring both present.
    if "java" in blob and "spring" in blob:
        score += 2
        reasons.append("java+spring")
    if any(k in blob for k in REMOTE_BONUS):
        score += 2
        reasons.append("remote")
    if any(k in blob for k in C2C_BONUS):
        score += 1
        reasons.append("contract/c2c")
    return (score, reasons)


def should_apply(title, description="", location=""):
    """True if this job fits Bob's CV well enough to spend a submit on it."""
    if os.environ.get("CV_MATCH_OFF") == "1":
        return True, 999, ["filter disabled"]
    min_score = int(os.environ.get("CV_MATCH_MIN", "2"))
    score, reasons = score_job(title, description, location)
    return (score >= min_score), score, reasons
