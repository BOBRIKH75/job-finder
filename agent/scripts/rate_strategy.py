#!/usr/bin/env python3
"""Rate-maximization strategy for Bob's C2C negotiation.

Goal: when a recruiter asks "what's your rate?", DON'T drop a flat number. Compute a
market-value target from the ROLE'S conditions (responsibility + remote/onsite + length +
clearance + direct-vs-vendor + niche stack + metro + urgency), anchor HIGH with a range
whose BOTTOM is the real target, and first extract scope + the client's approved budget.

Based on 2026 US market research for a Senior Java/Spring Boot contractor (10+ yrs, GC):
  national-remote senior Java C2C typical ~$95-115/hr; $120-140 with architecture/Kafka/
  K8s/AWS + fewer vendor layers; $145+ HCOL-metro or prime-direct.

Usage (standalone):
  python3 scripts/rate_strategy.py "immediate interview, onsite Denver, architecture lead, direct client, 3 months, kafka kubernetes aws"
Or import:
  from rate_strategy import compute_rate, build_rate_reply
"""
import re
import sys

BASE = 100          # national-remote senior Java C2C base ($/hr), 2026
FLOOR = 90          # never quote a target below this
CAP = 175           # credible ceiling for this profile


def compute_rate(desc: str) -> dict:
    """Return {target, low, high, factors[]} from the role description/conditions.
    target = the number to AIM for; quote range = [target, high] (bottom = target)."""
    t = (desc or "").lower()
    rate = float(BASE)
    factors = []

    def bump(mult_or_add, label, add=False):
        nonlocal rate
        if add:
            rate += mult_or_add
            factors.append(f"{label} (+${mult_or_add:.0f})")
        else:
            rate *= mult_or_add
            pct = int((mult_or_add - 1) * 100)
            factors.append(f"{label} ({pct:+d}%)")

    # Worksite
    if re.search(r"\bonsite|on-site|in-person|f2f\b", t):
        if re.search(r"reloc|travel", t):
            bump(1.28, "onsite+relocation")
        else:
            bump(1.12, "onsite")
    elif "hybrid" in t:
        bump(1.07, "hybrid")
    # (remote = baseline, no bump)

    # Contract length
    if re.search(r"\b(1|2|3)\s*month|short.term|short term", t):
        bump(1.12, "short contract")
    elif re.search(r"\b(12|18|24)\s*month|long.term|1\s*year|2\s*year", t):
        bump(0.93, "long contract (stability trade)")

    # Clearance
    if re.search(r"ts/sci|top secret|poly", t):
        bump(1.35, "TS/SCI clearance")
    elif re.search(r"clearance|secret|public trust", t):
        bump(1.15, "clearance")

    # Responsibility / scope
    if re.search(r"architect", t):
        bump(1.12, "architecture ownership")
    if re.search(r"\blead\b|team lead|tech lead", t):
        bump(1.12, "lead role")
    if re.search(r"on.call|production support|prod support", t):
        bump(1.07, "on-call/prod ownership")

    # Niche stack
    niche = 0
    for kw in ("kafka", "kubernetes", "k8s", "aws", "microservice"):
        if kw in t:
            niche += 1
    if niche >= 3:
        bump(1.10, f"niche stack x{niche}")
    elif niche >= 1:
        bump(1.05, f"niche stack x{niche}")

    # Client layers (direct vs vendor)
    if re.search(r"direct client|direct to client|prime vendor|implementation partner", t):
        bump(1.20, "direct/prime client")
    # (multi-vendor layers = they'll lowball; we hold firm, no downward bump here)

    # Metro
    if re.search(r"\b(nyc|new york|san francisco|sf|seattle|bay area|manhattan)\b", t):
        bump(1.18, "HCOL metro")

    # Urgency = THEIR leverage loss → anchor up, never discount
    if re.search(r"urgent|immediate|asap|right away|start now", t):
        bump(1.08, "urgency (anchor up, don't discount)")

    target = max(FLOOR, min(round(rate), CAP))
    # Quote range: bottom = target (recruiters negotiate DOWN from the top you give).
    low = target
    high = min(CAP, round(target * 1.17))
    return {"target": target, "low": low, "high": high, "factors": factors}


def build_rate_reply(recruiter_name: str, role: str, desc: str) -> tuple:
    """Build the strategic 'what's your rate?' reply: extract scope+budget FIRST, then
    anchor with a range whose BOTTOM is the computed market target."""
    r = compute_rate(desc)
    first = (recruiter_name or "").split()[0] if recruiter_name else ""
    greet = f"Hi {first}," if first else "Hi,"
    role_txt = role or "the role"

    subject = f"Re: {role_txt} — scope + C2C rate"
    body = (
        f"{greet}\n\n"
        f"Thanks for reaching out — this looks like a strong fit on the Spring Boot / "
        f"microservices / Kafka / Kubernetes / AWS side, which is exactly where I've spent "
        f"the last 10+ years.\n\n"
        f"Before I give a firm C2C number, a few quick questions so I quote accurately:\n"
        f"  1. Is this a direct client or through a vendor layer?\n"
        f"  2. Remote, hybrid, or onsite — any travel expectation?\n"
        f"  3. Contract length and likelihood of extension?\n"
        f"  4. Scope: IC vs architecture/lead ownership, and any on-call / production "
        f"responsibility?\n"
        f"  5. What budget range has the client approved for this role on C2C?\n\n"
        f"As a general anchor, senior Java contractors with my stack are landing in the "
        f"${r['low']}-{r['high']}/hr C2C range this year depending on responsibility — "
        f"I'll tailor the exact figure to the scope above. If it's architecture/lead with "
        f"on-call, it sits at the top of that range; a clean IC role lands at the bottom.\n\n"
        f"Happy to jump on a quick call.\n\n"
        f"Best,\nBob Rikh\n347-268-5917 | bobrikh75@gmail.com\n"
    )
    return subject, body, r


if __name__ == "__main__":
    desc = " ".join(sys.argv[1:]) or "remote c2c java spring boot"
    subj, body, r = build_rate_reply("", "Senior Java Developer", desc)
    print(f"=== computed target: ${r['target']}/hr   quote range: ${r['low']}-{r['high']}/hr ===")
    print("factors:", ", ".join(r["factors"]) or "(base only)")
    print("\n--- suggested reply ---")
    print("Subject:", subj)
    print(body)
