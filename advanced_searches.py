#!/usr/bin/env python3
"""Advanced Job Search Queries — multi-dimensional search across all platforms.

Searches by: title, skills, location, company type, contract type, seniority.
Covers: LinkedIn, Indeed, Dice, Google, Greenhouse, Ashby.
"""

# ═══════════════════════════════════════════════════════════════
# LINKEDIN ADVANCED SEARCHES (via jobspy — public, no login)
# ═══════════════════════════════════════════════════════════════

LINKEDIN_JOB_QUERIES = [
    # By Title
    "Senior Java Developer contract remote",
    "Java Backend Engineer contract",
    "Java Spring Boot Developer C2C",
    "Senior Software Engineer Java microservices",
    "Java Kafka Developer contract",
    "Platform Engineer Java Kubernetes",
    "Staff Software Engineer Java",
    # By Skills
    "Java Spring Boot Kafka Kubernetes contract",
    "Java AWS Docker microservices remote",
    "Java GraphQL MongoDB REST API contract",
    "Java Redis PostgreSQL backend developer",
    # By Location (Colorado + Remote)
    "Java developer remote USA contract",
    "Java developer Denver Colorado",
    "Java developer contract work from home",
    # By Company Type (C2C/Contract)
    "Java C2C corp-to-corp contract",
    "Java 1099 independent contractor",
    "Java W2 contract 6 months",
    "Java contract-to-hire remote",
]

# LinkedIn Advanced Search URLs (with filter parameters)
# f_JT=C → Contract, f_WT=2 → Remote, f_E=4 → Senior, f_TPR=r604800 → Past week
LINKEDIN_ADVANCED_URLS = [
    # Contract + Remote + Senior + Past week
    "https://www.linkedin.com/jobs/search/?keywords=Java%20Spring%20Boot&f_JT=C&f_WT=2&f_E=4&f_TPR=r604800",
    # Contract + Remote + Java Kafka
    "https://www.linkedin.com/jobs/search/?keywords=Java%20Kafka%20Kubernetes&f_JT=C&f_WT=2&f_TPR=r604800",
    # Contract + USA + C2C
    "https://www.linkedin.com/jobs/search/?keywords=Java%20C2C%20corp-to-corp&f_JT=C&f_WT=2&f_TPR=r604800",
    # Contract + Remote + Microservices
    "https://www.linkedin.com/jobs/search/?keywords=Java%20microservices%20backend&f_JT=C&f_WT=2&f_E=4&f_TPR=r604800",
    # Contract + Colorado
    "https://www.linkedin.com/jobs/search/?keywords=Java%20developer&f_JT=C&location=Colorado&f_TPR=r604800",
    # Contract + Remote + Docker AWS
    "https://www.linkedin.com/jobs/search/?keywords=Java%20Docker%20AWS%20contract&f_JT=C&f_WT=2&f_TPR=r2592000",
    # All experience levels + Contract + Remote (wider net)
    "https://www.linkedin.com/jobs/search/?keywords=Java%20Spring%20Boot%20contract%20remote&f_JT=C&f_WT=2",
    # Contract + Remote + GraphQL MongoDB
    "https://www.linkedin.com/jobs/search/?keywords=Java%20GraphQL%20MongoDB&f_JT=C&f_WT=2&f_TPR=r604800",
]

# LinkedIn People Search URLs (find recruiters)
# network=S → 2nd connections, title filter
LINKEDIN_RECRUITER_URLS = [
    # Java recruiters in USA
    "https://www.linkedin.com/search/results/people/?keywords=Java%20recruiter%20C2C&geoUrn=%5B%22103644278%22%5D&origin=FACETED_SEARCH",
    # Technical recruiters at staffing companies
    "https://www.linkedin.com/search/results/people/?keywords=technical%20recruiter%20Java%20Spring%20Boot&geoUrn=%5B%22103644278%22%5D",
    # Hiring managers Java backend
    "https://www.linkedin.com/search/results/people/?keywords=hiring%20manager%20Java%20backend%20developer&geoUrn=%5B%22103644278%22%5D",
    # Talent acquisition Java
    "https://www.linkedin.com/search/results/people/?keywords=talent%20acquisition%20Java%20contract&geoUrn=%5B%22103644278%22%5D",
]

# LinkedIn Company Search URLs
LINKEDIN_COMPANY_URLS = [
    "https://www.linkedin.com/search/results/companies/?keywords=Java%20staffing%20C2C&origin=SWITCH_SEARCH_VERTICAL",
    "https://www.linkedin.com/search/results/companies/?keywords=IT%20staffing%20contract%20Java&origin=SWITCH_SEARCH_VERTICAL",
]

# ═══════════════════════════════════════════════════════════════
# LINKEDIN RECRUITER SEARCHES (find people, not jobs)
# ═══════════════════════════════════════════════════════════════

LINKEDIN_RECRUITER_QUERIES = [
    # By recruiter type
    "Java recruiter C2C contract staffing",
    "Technical recruiter Java Spring Boot",
    "IT staffing recruiter Java developer",
    "Talent acquisition Java backend",
    # By company (known C2C vendors)
    "recruiter Collabera Java",
    "recruiter TEKsystems Java developer",
    "recruiter Pyramid Consulting Java",
    "recruiter Randstad technology Java",
    "recruiter Robert Half Java",
    "recruiter Insight Global Java",
    "recruiter Kforce Java developer",
    # By seniority
    "senior recruiter Java backend USA",
    "lead recruiter software engineering contract",
    "hiring manager Java microservices",
]

# ═══════════════════════════════════════════════════════════════
# LINKEDIN COMPANY SEARCHES (find companies hiring)
# ═══════════════════════════════════════════════════════════════

LINKEDIN_COMPANY_QUERIES = [
    "companies hiring Java developers remote",
    "startups hiring Java Spring Boot engineers",
    "fintech companies Java backend openings",
    "healthcare tech Java developer positions",
    "e-commerce Java microservices hiring",
]

# ═══════════════════════════════════════════════════════════════
# INDEED ADVANCED SEARCHES
# ═══════════════════════════════════════════════════════════════

INDEED_QUERIES = [
    # C2C specific
    {"term": "Java Spring Boot C2C contract remote", "location": "USA"},
    {"term": "Java developer corp-to-corp", "location": "USA"},
    {"term": "Java C2C 1099 contractor", "location": "Remote"},
    # By skills
    {"term": "Java Kafka Kubernetes contract", "location": "USA"},
    {"term": "Java microservices Docker AWS contract", "location": "USA"},
    {"term": "Java GraphQL MongoDB developer contract", "location": "Remote"},
    {"term": "Java Spring Cloud backend contract", "location": "USA"},
    # By location
    {"term": "Java developer contract", "location": "Colorado"},
    {"term": "Java developer contract", "location": "Denver, CO"},
    {"term": "Java backend remote contract", "location": "USA"},
    # By seniority
    {"term": "Senior Java developer contract remote", "location": "USA"},
    {"term": "Lead Java engineer contract", "location": "USA"},
    {"term": "Staff Java developer contract", "location": "Remote"},
    # By rate
    {"term": "Java developer $70 $80 $90 hourly contract", "location": "USA"},
]

# ═══════════════════════════════════════════════════════════════
# DICE SEARCHES (via Google site:dice.com)
# ═══════════════════════════════════════════════════════════════

DICE_QUERIES = [
    "site:dice.com Java Spring Boot C2C contract remote",
    "site:dice.com Java developer corp-to-corp",
    "site:dice.com Java Kafka Kubernetes contract",
    "site:dice.com Senior Java backend developer contract",
    "site:dice.com Java microservices AWS Docker contract",
]

# ═══════════════════════════════════════════════════════════════
# TARGET COMPANIES (for direct career page scanning)
# ═══════════════════════════════════════════════════════════════

TARGET_COMPANIES_GREENHOUSE = [
    # Tech Giants
    "affirm", "stripe", "datadog", "cloudflare", "elastic", "confluent",
    "cockroachlabs", "fivetran", "clickhouse", "singlestore", "marqeta",
    "newrelic", "okta", "twilio", "brex", "chime", "hightouch", "planetscale",
    # Fintech
    "plaid", "robinhood", "coinbase", "kraken", "blockfi",
    # SaaS
    "hubspot", "zendesk", "intercom", "segment", "amplitude",
    # Data/AI
    "databricks", "snowflake", "dbt-labs", "airbyte", "prefect",
    # DevTools
    "hashicorp", "grafana", "snyk", "sonatype", "jfrog", "launchdarkly",
]

TARGET_COMPANIES_ASHBY = [
    "anthropic", "notion", "ramp", "retool", "linear", "vercel",
    "supabase", "resend", "cal-com", "dbt-labs", "airbyte", "temporal", "neon",
]

# ═══════════════════════════════════════════════════════════════
# C2C VENDORS (for recruiter search)
# ═══════════════════════════════════════════════════════════════

C2C_VENDORS = [
    "Collabera", "TEKsystems", "Pyramid Consulting", "Skiltrek",
    "Randstad", "Robert Half", "Insight Global", "Kforce", "Modis",
    "Mastech", "RIT Solutions", "Amerit Consulting", "Han IT Staffing",
    "Multivision", "WorkNovas", "Wipro", "Infosys", "TCS", "HCL",
    "Cognizant", "Mphasis", "Hexaware", "Cyient",
]

# Only USA-based vendors (filter out India-based)
USA_C2C_VENDORS = [
    "Collabera", "TEKsystems", "Pyramid Consulting", "Skiltrek",
    "Randstad", "Robert Half", "Insight Global", "Kforce", "Modis",
    "Mastech", "RIT Solutions", "Amerit Consulting",
]


def get_all_job_queries() -> list[dict]:
    """Get all search queries for all platforms."""
    queries = []
    for q in LINKEDIN_JOB_QUERIES:
        queries.append({"platform": "linkedin", "type": "job", "query": q})
    for q in INDEED_QUERIES:
        queries.append({"platform": "indeed", "type": "job", "query": q["term"], "location": q["location"]})
    for q in DICE_QUERIES:
        queries.append({"platform": "dice", "type": "job", "query": q})
    return queries


def get_recruiter_queries() -> list[str]:
    """Get all recruiter search queries for LinkedIn."""
    return LINKEDIN_RECRUITER_QUERIES


def get_company_queries() -> list[str]:
    """Get all company search queries."""
    return LINKEDIN_COMPANY_QUERIES


if __name__ == "__main__":
    all_q = get_all_job_queries()
    print(f"Total search queries: {len(all_q)}")
    print(f"  LinkedIn jobs: {len(LINKEDIN_JOB_QUERIES)}")
    print(f"  LinkedIn recruiters: {len(LINKEDIN_RECRUITER_QUERIES)}")
    print(f"  LinkedIn companies: {len(LINKEDIN_COMPANY_QUERIES)}")
    print(f"  Indeed: {len(INDEED_QUERIES)}")
    print(f"  Dice: {len(DICE_QUERIES)}")
    print(f"  Target companies (Greenhouse): {len(TARGET_COMPANIES_GREENHOUSE)}")
    print(f"  Target companies (Ashby): {len(TARGET_COMPANIES_ASHBY)}")
    print(f"  C2C vendors (USA): {len(USA_C2C_VENDORS)}")
