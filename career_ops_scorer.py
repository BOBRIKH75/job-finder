#!/usr/bin/env python3
"""
Career-Ops 10-Dimension Job Scorer
Inspired by santifer.io/career-ops-system — adapted for Bob Rikh's C2C pipeline.

Evaluates jobs across 10 weighted dimensions, produces A-F grade + numeric score.
Integrates with existing keyword_matcher.py for skills alignment.
"""
import re
from dataclasses import dataclass, field
from keyword_matcher import MY_SKILLS, extract, match as keyword_match

# ── Bob's Profile Constants ──
TARGET_RATE_MIN = 55
TARGET_RATE_MAX = 90
TARGET_LOCATION = 'parker, co'
PREFERRED_LOCATIONS = ['remote', 'colorado', 'denver', 'parker', 'aurora', 'centennial']
SENIORITY_KEYWORDS = {
    'senior': 3, 'sr': 3, 'lead': 4, 'principal': 5, 'staff': 5,
    'architect': 5, 'mid': 2, 'junior': 1, 'entry': 1,
}
TARGET_SENIORITY = 3  # senior level
PREFERRED_COMPANY_STAGES = ['growth', 'enterprise', 'mid-size']

CORE_STACK = {'java', 'spring boot', 'kafka', 'kubernetes', 'microservices',
              'docker', 'aws', 'graphql', 'mongodb', 'rest'}


@dataclass
class DimensionScore:
    name: str
    score: float  # 1.0 - 5.0
    weight: str   # 'gate-pass', 'high', 'medium', 'low'
    reason: str = ''


@dataclass
class JobEvaluation:
    dimensions: list = field(default_factory=list)
    final_score: float = 0.0
    grade: str = 'F'
    verdict: str = ''
    matched_skills: set = field(default_factory=set)
    gaps: set = field(default_factory=set)
    match_pct: int = 0


def _detect_seniority(text: str) -> int:
    """Detect seniority level from job text. Returns 1-5."""
    text_lower = text.lower()
    # Check for explicit junior/entry signals first
    if any(k in text_lower for k in ['junior', 'entry level', 'entry-level', 'intern ', 'graduate']):
        return 1
    best = 2  # default mid-level
    for kw, level in SENIORITY_KEYWORDS.items():
        if kw in text_lower:
            best = max(best, level)
    return best


def _detect_compensation(text: str) -> tuple:
    """Extract rate/salary info. Returns (min, max, interval)."""
    # Hourly patterns: $55-90/hr, $55/hr - $90/hr, $55 - $90 per hour
    hourly = re.findall(r'\$(\d{2,3})\s*[-–to]+\s*\$?(\d{2,3})\s*(?:/hr|per hour|hourly|/hour)', text, re.I)
    if hourly:
        return float(hourly[0][0]), float(hourly[0][1]), 'hourly'
    single_hr = re.findall(r'\$(\d{2,3})\s*(?:/hr|per hour|hourly|/hour)', text, re.I)
    if single_hr:
        rate = float(single_hr[0])
        return rate, rate, 'hourly'
    # Annual patterns
    annual = re.findall(r'\$(\d{3})[,.]?(\d{3})\s*[-–to]+\s*\$?(\d{3})[,.]?(\d{3})', text)
    if annual:
        mn = float(annual[0][0] + annual[0][1])
        mx = float(annual[0][2] + annual[0][3])
        return mn, mx, 'annual'
    return 0, 0, 'unknown'


def _detect_remote(text: str) -> str:
    """Detect work arrangement. Returns 'remote', 'hybrid', or 'onsite'."""
    t = text.lower()
    if 'fully remote' in t or 'remote only' in t or '100% remote' in t:
        return 'remote'
    if 'remote' in t and 'hybrid' not in t:
        return 'remote'
    if 'hybrid' in t:
        return 'hybrid'
    return 'onsite'


def _detect_c2c(text: str) -> bool:
    """Check if job explicitly mentions C2C/corp-to-corp."""
    t = text.lower()
    return any(k in t for k in ['c2c', 'corp-to-corp', 'corp to corp', '1099', 'w2/c2c', 'w2 or c2c'])


def _detect_company_stage(text: str) -> str:
    """Guess company stage from signals in text."""
    t = text.lower()
    # Check growth BEFORE startup (Series C is growth, not startup)
    if any(k in t for k in ['growth', 'scaling', 'series c', 'series d', 'mid-size']):
        return 'growth'
    if any(k in t for k in ['fortune 500', 'enterprise', 'global', 'established']):
        return 'enterprise'
    if any(k in t for k in ['startup', 'seed', 'series a', 'series b', 'early stage']):
        return 'startup'
    return 'unknown'


def _detect_urgency(text: str) -> int:
    """Detect hiring urgency. Returns 1-5."""
    t = text.lower()
    if any(k in t for k in ['immediate', 'asap', 'urgent', 'start immediately']):
        return 5
    if any(k in t for k in ['immediate start', 'right away', 'this week']):
        return 5
    if any(k in t for k in ['2 weeks', 'quick start', 'fast hire']):
        return 4
    if any(k in t for k in ['soon', 'quickly']):
        return 3
    return 2


def score_role_match(text: str, matched_skills: set) -> DimensionScore:
    """Dimension 1: Role Match — alignment between JD requirements and CV proof points."""
    core_matched = CORE_STACK & matched_skills
    core_pct = len(core_matched) / len(CORE_STACK) if CORE_STACK else 0

    # Check if role title aligns with Java backend
    t = text.lower()
    role_signals = sum(1 for k in ['java', 'backend', 'back-end', 'back end', 'server',
                                    'microservice', 'api', 'platform'] if k in t)
    role_fit = min(role_signals / 3, 1.0)

    # Weighted: core stack match matters most, role title is secondary
    score = (core_pct * 0.6 + role_fit * 0.4) * 5
    # Floor: if any core skills match AND role title fits, minimum 2.0
    if core_pct > 0 and role_fit > 0:
        score = max(score, 2.0)
    score = max(1.0, min(5.0, score))

    return DimensionScore(
        name='Role Match', score=round(score, 2), weight='gate-pass',
        reason=f'{len(core_matched)}/{len(CORE_STACK)} core stack matched, role_fit={role_fit:.1f}'
    )


def score_skills_alignment(matched_skills: set, gaps: set, match_pct: int) -> DimensionScore:
    """Dimension 2: Skills Alignment — tech stack overlap."""
    # Direct mapping: 80%+ = 5, 60-79% = 4, 40-59% = 3, 20-39% = 2, <20% = 1
    if match_pct >= 80:
        score = 4.5 + (match_pct - 80) / 40  # 80%=4.5, 100%=5.0
    elif match_pct >= 60:
        score = 3.5 + (match_pct - 60) / 40  # 60%=3.5, 80%=4.0
    elif match_pct >= 40:
        score = 2.5 + (match_pct - 40) / 40
    elif match_pct >= 20:
        score = 1.5 + (match_pct - 20) / 40
    else:
        score = 1.0 + match_pct / 40

    score = max(1.0, min(5.0, score))
    return DimensionScore(
        name='Skills Alignment', score=round(score, 2), weight='gate-pass',
        reason=f'{match_pct}% match, {len(matched_skills)} matched, {len(gaps)} gaps'
    )


def score_seniority(text: str) -> DimensionScore:
    """Dimension 3: Seniority — stretch level and negotiability."""
    detected = _detect_seniority(text)
    diff = abs(detected - TARGET_SENIORITY)

    if diff == 0:
        score = 5.0
    elif diff == 1:
        score = 4.0 if detected > TARGET_SENIORITY else 3.5  # stretch up = slightly better
    else:
        score = 2.0  # 2+ levels away = poor fit

    return DimensionScore(
        name='Seniority', score=score, weight='high',
        reason=f'detected={detected}, target={TARGET_SENIORITY}, diff={diff}'
    )


def score_compensation(text: str, min_rate=0, max_rate=0, interval='') -> DimensionScore:
    """Dimension 4: Compensation — market rate vs target."""
    mn, mx, intv = _detect_compensation(text)
    # Override with structured data if available
    if min_rate and max_rate and interval:
        mn, mx, intv = float(min_rate), float(max_rate), interval

    if intv == 'unknown' or (mn == 0 and mx == 0):
        # No comp info — neutral score
        return DimensionScore(name='Compensation', score=3.0, weight='high',
                              reason='no compensation data found')

    if intv == 'annual':
        # Convert to hourly (2080 hours/year)
        mn, mx = mn / 2080, mx / 2080

    # Score based on overlap with target range
    if mx < TARGET_RATE_MIN:
        score = max(1.0, 1.0 + (mx / TARGET_RATE_MIN) * 2)
    elif mn > TARGET_RATE_MAX:
        score = 5.0  # above range = great
    elif mn >= TARGET_RATE_MIN and mx <= TARGET_RATE_MAX:
        score = 4.5  # within range
    elif mx >= TARGET_RATE_MIN:
        overlap = min(mx, TARGET_RATE_MAX) - max(mn, TARGET_RATE_MIN)
        range_size = TARGET_RATE_MAX - TARGET_RATE_MIN
        score = 3.0 + (overlap / range_size) * 2
    else:
        score = 2.0

    score = max(1.0, min(5.0, score))
    return DimensionScore(
        name='Compensation', score=round(score, 2), weight='high',
        reason=f'${mn:.0f}-${mx:.0f}/hr vs target ${TARGET_RATE_MIN}-${TARGET_RATE_MAX}/hr'
    )


def score_geographic(text: str) -> DimensionScore:
    """Dimension 5: Geographic — remote/hybrid/onsite feasibility."""
    arrangement = _detect_remote(text)
    t = text.lower()

    if arrangement == 'remote':
        score = 5.0
    elif arrangement == 'hybrid':
        # Check if location is near
        if any(loc in t for loc in PREFERRED_LOCATIONS):
            score = 4.0
        else:
            score = 2.5
    else:  # onsite
        if any(loc in t for loc in PREFERRED_LOCATIONS):
            score = 3.5
        else:
            score = 1.5

    return DimensionScore(
        name='Geographic', score=score, weight='medium',
        reason=f'{arrangement}, location match={any(loc in t for loc in PREFERRED_LOCATIONS)}'
    )


def score_company_stage(text: str) -> DimensionScore:
    """Dimension 6: Company Stage — startup/growth/enterprise fit."""
    stage = _detect_company_stage(text)
    scores = {'enterprise': 4.5, 'growth': 4.0, 'startup': 3.0, 'unknown': 3.0}
    score = scores.get(stage, 3.0)
    return DimensionScore(name='Company Stage', score=score, weight='medium',
                          reason=f'detected={stage}')


def score_product_market_fit(text: str) -> DimensionScore:
    """Dimension 7: Product-Market Fit — problem domain resonance."""
    t = text.lower()
    # Domains Bob has deep experience in
    strong_domains = ['telecom', 'cable', 'isp', 'networking', 'iot', 'saas', 'fintech',
                      'e-commerce', 'platform', 'api platform', 'data pipeline', 'event-driven']
    matches = sum(1 for d in strong_domains if d in t)
    score = min(5.0, 2.5 + matches * 0.8)
    return DimensionScore(name='Product-Market Fit', score=round(score, 2), weight='medium',
                          reason=f'{matches} domain signals found')


def score_growth_trajectory(text: str) -> DimensionScore:
    """Dimension 8: Growth Trajectory — career ladder visibility."""
    t = text.lower()
    growth_signals = ['career growth', 'promotion', 'leadership', 'mentor', 'lead',
                      'architect path', 'principal', 'staff', 'director', 'vp']
    matches = sum(1 for s in growth_signals if s in t)
    score = min(5.0, 2.0 + matches * 0.8)
    return DimensionScore(name='Growth Trajectory', score=round(score, 2), weight='medium',
                          reason=f'{matches} growth signals')


def score_interview_likelihood(text: str, match_pct: int, is_c2c: bool) -> DimensionScore:
    """Dimension 9: Interview Likelihood — callback probability."""
    score = 2.0

    # High skill match = higher callback
    if match_pct >= 80:
        score += 1.5
    elif match_pct >= 60:
        score += 1.0
    elif match_pct >= 40:
        score += 0.5

    # C2C = vendor relationship, higher callback
    if is_c2c:
        score += 1.0

    # Green card / no sponsorship mentioned = they want it
    t = text.lower()
    if any(k in t for k in ['green card', 'no sponsorship', 'usc/gc', 'gc', 'authorized']):
        score += 0.5

    score = max(1.0, min(5.0, score))
    return DimensionScore(name='Interview Likelihood', score=round(score, 2), weight='high',
                          reason=f'match={match_pct}%, c2c={is_c2c}')


def score_timeline(text: str) -> DimensionScore:
    """Dimension 10: Timeline — closing speed and hiring urgency."""
    urgency = _detect_urgency(text)
    score = float(urgency)
    return DimensionScore(name='Timeline', score=score, weight='low',
                          reason=f'urgency={urgency}/5')


def calculate_final_score(dimensions: list) -> tuple:
    """
    Calculate weighted final score and grade.
    Gate-pass dimensions: if either < 2.5, final score is capped at 2.5.
    """
    weights = {'gate-pass': 2.0, 'high': 1.5, 'medium': 1.0, 'low': 0.5}
    total_weight = 0
    weighted_sum = 0
    gate_pass_failed = False

    for d in dimensions:
        w = weights.get(d.weight, 1.0)
        weighted_sum += d.score * w
        total_weight += w
        if d.weight == 'gate-pass' and d.score < 2.5:
            gate_pass_failed = True

    raw_score = weighted_sum / total_weight if total_weight > 0 else 0

    if gate_pass_failed:
        raw_score = min(raw_score, 2.5)

    final = round(max(1.0, min(5.0, raw_score)), 2)

    # Grade mapping
    if final >= 4.5:
        grade = 'A'
    elif final >= 4.0:
        grade = 'B'
    elif final >= 3.0:
        grade = 'C'
    elif final >= 2.0:
        grade = 'D'
    else:
        grade = 'F'

    return final, grade


def get_verdict(grade: str, match_pct: int, is_c2c: bool) -> str:
    """Generate actionable verdict."""
    if grade in ('A', 'B') and match_pct >= 70:
        return '🔥 STRONG MATCH — Apply immediately'
    elif grade in ('A', 'B'):
        return '✅ GOOD FIT — Apply, tailor CV to gaps'
    elif grade == 'C' and match_pct >= 60:
        return '📋 DECENT — Apply if nothing better, add keywords'
    elif grade == 'C':
        return '⚠️ MARGINAL — Only if C2C confirmed and rate good'
    else:
        return '❌ SKIP — Poor fit, move on'


def evaluate_job(job_text: str, title: str = '', company: str = '',
                 min_rate: float = 0, max_rate: float = 0,
                 interval: str = '') -> JobEvaluation:
    """
    Full 10-dimension evaluation of a job posting.
    This is the main entry point — call with job description text.
    """
    # Step 1: Keyword matching (reuses existing keyword_matcher)
    matched_skills, raw_gaps = keyword_match(job_text)

    # Filter gaps aggressively — only keep words that look like real tech terms
    EXTRA_NOISE = {
        'tech', 'stack', 'boot', 'developer', 'engineer', 'senior', 'lead',
        'backend', 'frontend', 'fullstack', 'full', 'remote', 'hybrid', 'onsite',
        'contract', 'rate', 'location', 'company', 'client', 'start', 'immediately',
        'urgent', 'scaling', 'fast', 'growth', 'series', 'fortune', 'global',
        'career', 'path', 'green', 'card', 'sponsorship', 'authorized', 'fully',
        'staffing', 'consulting', 'pyramid', 'skiltrek', 'collabera', 'teksystems',
        'telecom', 'saas', 'platform', 'domain', 'architecture', 'patterns',
        'apache', 'level', 'years', 'experience', 'required', 'preferred',
        'must', 'strong', 'plus', 'nice', 'have', 'looking', 'join',
        'denver', 'colorado', 'parker', 'nyc', 'francisco',
        'name', 'please', 'share', 'updated', 'resume', 'months', 'duration',
        'requirement', 'requirements', 'role', 'title', 'team', 'work',
        'build', 'help', 'make', 'take', 'need', 'like', 'able', 'good',
        'best', 'high', 'well', 'also', 'more', 'than', 'other', 'about',
        'would', 'which', 'when', 'what', 'each', 'every', 'some', 'many',
        'first', 'last', 'next', 'only', 'just', 'over', 'under', 'after',
        'before', 'between', 'through', 'during', 'without', 'within',
        'across', 'along', 'around', 'behind', 'below', 'above',
        'opportunity', 'position', 'candidate', 'qualifications', 'skills',
        'knowledge', 'ability', 'responsible', 'ensure', 'deliver', 'drive',
        'communicate', 'collaborate', 'maintain', 'create', 'provide',
        'support', 'manage', 'implement', 'develop', 'design', 'solutions',
        'system', 'systems', 'application', 'applications', 'software',
        'technology', 'technical', 'environment', 'complex', 'multiple',
        'various', 'core', 'based', 'related', 'ideal', 'proven',
        'minimum', 'salary', 'benefits', 'equal', 'employer',
        'description', 'overview', 'summary', 'responsibilities',
        'hiring', 'process', 'interview', 'offer', 'apply', 'submit',
        'send', 'contact', 'email', 'phone', 'call', 'reach',
        'fundamentals', 'principles', 'concepts', 'methodologies',
        'tools', 'frameworks', 'libraries', 'services', 'components',
        'features', 'products', 'projects', 'tasks', 'goals',
    }
    gaps = {g for g in raw_gaps if g not in EXTRA_NOISE and len(g) >= 3}

    match_pct = int(len(matched_skills) / max(len(matched_skills) + len(gaps), 1) * 100)

    full_text = f'{title} {company} {job_text}'
    is_c2c = _detect_c2c(full_text)

    # Step 2: Score all 10 dimensions
    dimensions = [
        score_role_match(full_text, matched_skills),
        score_skills_alignment(matched_skills, gaps, match_pct),
        score_seniority(full_text),
        score_compensation(full_text, min_rate, max_rate, interval),
        score_geographic(full_text),
        score_company_stage(full_text),
        score_product_market_fit(full_text),
        score_growth_trajectory(full_text),
        score_interview_likelihood(full_text, match_pct, is_c2c),
        score_timeline(full_text),
    ]

    # Step 3: Calculate final score + grade
    final_score, grade = calculate_final_score(dimensions)
    verdict = get_verdict(grade, match_pct, is_c2c)

    return JobEvaluation(
        dimensions=dimensions,
        final_score=final_score,
        grade=grade,
        verdict=verdict,
        matched_skills=matched_skills,
        gaps=gaps,
        match_pct=match_pct,
    )


def format_evaluation(eval: JobEvaluation, title: str = '', company: str = '') -> str:
    """Format evaluation as readable text output."""
    lines = []
    if title or company:
        lines.append(f'\n{"═"*60}')
        lines.append(f'  📊 {title} @ {company}')
        lines.append(f'{"═"*60}')

    lines.append(f'\n  Final Score: {eval.final_score}/5.0 | Grade: {eval.grade}')
    lines.append(f'  Verdict: {eval.verdict}')
    lines.append(f'\n  ── 10 Dimensions ──')

    for d in eval.dimensions:
        bar = '█' * int(d.score) + '░' * (5 - int(d.score))
        lines.append(f'  {d.name:<22} {d.score:.1f}/5 {bar} [{d.weight}] {d.reason}')

    lines.append(f'\n  ── Skills ──')
    lines.append(f'  ✅ Matched ({len(eval.matched_skills)}): {", ".join(sorted(eval.matched_skills)[:15])}')
    if eval.gaps:
        lines.append(f'  ⚠️  Gaps ({len(eval.gaps)}): {", ".join(sorted(eval.gaps)[:10])}')
    lines.append(f'  📊 Match: {eval.match_pct}%')

    return '\n'.join(lines)
