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
import re

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
    "c++", "c/c++", " golang", "golang ", "rust ", " rust", "scala ", "elixir", "perl",
    "frontend only", "front-end only", "ui/ux", "designer", "sales ", "account executive",
    "recruiter", "nurse", "nursing", "driver", "warehouse", "cashier", "data entry",
    "qa manual", "manual tester", "servicenow", "sharepoint", "cobol", "mainframe",
    "android developer", "ios developer", "mobile developer", "golang only", "python developer",
    "data scientist", "machine learning engineer", "devops engineer only", "network engineer",
    "security engineer", "security architect", "solutions engineer", "solutions architect",
    "sales engineer", "support engineer", "sdet", "qa engineer", "data engineer",
    "analytics engineer", "site reliability", "engineering manager", "program manager",
    "data architect", "enterprise architect", "ai engineer", "ai integration", "llm ", "prompt engineer",
    "business analyst", "project manager", "scrum master", "product manager",
    # Off-stack titles seen being applied to on Dice (Nov 2026 audit) — not Bob's lane.
    "django", "flask", "workfront", "rpa ", "rpa developer", "uipath", "blue prism",
    "ai architect", "ai agent", "solution architect", "mulesoft", "pega", "appian",
)


# Other-language/stack tags in the TITLE (e.g. "Backend Engineer (Ruby)", "Python Engineer"):
# skip unless the title also says Java.
_OTHER_LANG_TITLE = re.compile(
    r"\b(ruby|rails|python|golang|go|rust|scala|php|c\+\+|c#|\.net|node(\.?js)?|typescript|react|"
    r"angular|vue|kotlin|swift|elixir|perl|clojure|haskell|android|ios|flutter|unity|unreal)\b", re.I)
# Titles that are clearly in Bob's lane even when the JD is thin.
_LANE_TITLE = re.compile(
    r"\b(back[- ]?end|backend|platform|api|integration|services?|distributed|infrastructure|"
    r"software (engineer|developer)|java)\b", re.I)
# Stack signals that make a non-Java-worded JD a credible fit for the CV (needs >= 3).
_STACK_SIGNALS = ("microservice", "kafka", "kubernetes", "aws", "distributed system",
                  "rest api", "restful", "event-driven", "spring", "jvm", "grpc", "postgres")


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

    # Title must be an engineering/dev role at all (JD text alone must not rescue e.g. "Operations Associate").
    if not re.search(r"\b(engineer|developer|programmer|architect|swe|sde|software|backend|back-end|"
                     r"platform|java)\b", t):
        return (-50, ["title is not an engineering role"])

    # Other-language title tag without Java in the title -> different stack, skip.
    if "java" not in t and _OTHER_LANG_TITLE.search(t):
        return (-100, ["title is another language/stack"])

    # Must look like a Java/backend role somewhere.
    if not any(k in blob for k in CORE_MUST):
        return (-10, ["no core Java/backend signal"])

    score = 0
    hits = [k for k in POSITIVE if k in blob]
    score += len(set(hits))
    if hits:
        reasons.append(f"skills:{len(set(hits))}")
    # Strong core boost if Java + Spring both present.
    if "java" in t and "javascript" not in t:
        score += 3                     # "Java Developer / Senior Java Engineer" in the TITLE
        reasons.append("java-in-title")
    if re.search(r"back[- ]?end", t):
        score += 2
        reasons.append("backend-in-title")
    if "java" in blob and "spring" in blob:
        score += 2
        reasons.append("java+spring")
    if any(k in blob for k in REMOTE_BONUS):
        score += 2
        reasons.append("remote")
    if any(k in blob for k in C2C_BONUS):
        score += 1
        reasons.append("contract/c2c")
    # REQUIRE a real Java/backend skill signal — remote/C2C are BONUSES, not qualifiers.
    # A generic "Software Engineer" with NO java/spring/backend/microservice skill (score
    # coming only from remote/contract) is NOT a confirmed CV fit → force a skip. This is
    # why Greenhouse was disabled (Figma "Software Engineer, C++", Toast Ruby/React passed
    # on the generic title). Now they don't.
    _real_skill = any(k in blob for k in (
        "java", "spring", "spring boot", "microservice", "microservices",
        "backend", "back-end", "back end", "j2ee", "jakarta"))
    if not _real_skill:
        # Platform/API/Integration/Software Engineer titles whose JD is rich in Bob's stack
        # (microservices, Kafka, Kubernetes, AWS, distributed systems...) are credible fits.
        _stack = sum(1 for k in _STACK_SIGNALS if k in blob)
        if _LANE_TITLE.search(t) and _stack >= 3:
            return (max(score, 2), reasons + [f"stack-rich:{_stack}"])
        return (-5, ["no real Java/Spring/backend skill (generic title only)"])
    return (score, reasons)


def should_apply(title, description="", location=""):
    """True if this job fits Bob's CV well enough to spend a submit on it."""
    if os.environ.get("CV_MATCH_OFF") == "1":
        return True, 999, ["filter disabled"]
    min_score = int(os.environ.get("CV_MATCH_MIN", "2"))
    score, reasons = score_job(title, description, location)
    return (score >= min_score), score, reasons
