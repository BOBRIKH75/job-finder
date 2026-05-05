#!/usr/bin/env python3
"""
Unit Tests for Career-Ops 10-Dimension Scorer
Tests every dimension, edge cases, grade calculation, and integration with keyword_matcher.
Run: cd ~/Downloads/CV && python3 -m pytest test_career_ops_scorer.py -v
"""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from career_ops_scorer import (
    evaluate_job, calculate_final_score, get_verdict, format_evaluation,
    score_role_match, score_skills_alignment, score_seniority,
    score_compensation, score_geographic, score_company_stage,
    score_product_market_fit, score_growth_trajectory,
    score_interview_likelihood, score_timeline,
    _detect_seniority, _detect_compensation, _detect_remote,
    _detect_c2c, _detect_company_stage, _detect_urgency,
    DimensionScore, JobEvaluation,
    TARGET_RATE_MIN, TARGET_RATE_MAX, CORE_STACK,
)


# ══════════════════════════════════════════════════════════════
# HELPER: Sample job descriptions for testing
# ══════════════════════════════════════════════════════════════

PERFECT_JOB = """
Senior Java Backend Developer — C2C Contract — Remote
Company: TechGrowth Solutions (Series C, scaling fast)

We need a Senior Java developer for our microservices platform.
Tech stack: Java 17, Spring Boot, Apache Kafka, Kubernetes, Docker, AWS,
MongoDB, GraphQL, REST APIs, Redis, PostgreSQL.
CI/CD with Jenkins, Maven, JUnit 5, Mockito.
Event-driven architecture, design patterns, multithreading.

Rate: $75-85/hr C2C (corp-to-corp)
Location: Fully remote, US-based
No sponsorship required — Green Card or USC only.
Start: Immediately, urgent hire.
Career growth: path to Lead/Architect role.
Domain: Telecom SaaS platform.
"""

WEAK_JOB = """
Junior Data Entry Clerk
Company: Unknown Corp
Location: New York, onsite only
Salary: $35,000/year
Requirements: Excel, typing speed 60 WPM, attention to detail.
"""

MEDIUM_JOB = """
Java Developer — Contract
Company: Pyramid Consulting (staffing)
Location: Denver, CO (hybrid)
Rate: $60-70/hr
Requirements: Java, Spring Boot, REST APIs, SQL, Git, Agile, Scrum.
Must have 5+ years experience. W2 or C2C available.
"""

NO_COMP_JOB = """
Senior Java Engineer — Remote
Requirements: Java, Spring Boot, Kafka, Kubernetes, Docker, AWS, MongoDB.
Microservices architecture. Agile team.
"""


# ══════════════════════════════════════════════════════════════
# DETECTION HELPERS
# ══════════════════════════════════════════════════════════════

class TestDetectSeniority:
    def test_senior(self):
        assert _detect_seniority('Senior Java Developer') == 3

    def test_lead(self):
        assert _detect_seniority('Lead Backend Engineer') == 4

    def test_principal(self):
        assert _detect_seniority('Principal Software Engineer') == 5

    def test_staff(self):
        assert _detect_seniority('Staff Engineer') == 5

    def test_junior(self):
        assert _detect_seniority('Junior Developer') == 1

    def test_no_signal(self):
        assert _detect_seniority('Java Developer') == 2  # default

    def test_multiple_picks_highest(self):
        assert _detect_seniority('Senior to Lead path, architect level') == 5


class TestDetectCompensation:
    def test_hourly_range(self):
        mn, mx, intv = _detect_compensation('Rate: $65-85/hr')
        assert mn == 65 and mx == 85 and intv == 'hourly'

    def test_hourly_per_hour(self):
        mn, mx, intv = _detect_compensation('$70 - $90 per hour')
        assert mn == 70 and mx == 90 and intv == 'hourly'

    def test_single_rate(self):
        mn, mx, intv = _detect_compensation('Pays $75/hr')
        assert mn == 75 and mx == 75 and intv == 'hourly'

    def test_annual(self):
        mn, mx, intv = _detect_compensation('Salary: $120,000 - $160,000')
        assert mn == 120000 and mx == 160000 and intv == 'annual'

    def test_no_comp(self):
        mn, mx, intv = _detect_compensation('Great opportunity!')
        assert mn == 0 and mx == 0 and intv == 'unknown'


class TestDetectRemote:
    def test_fully_remote(self):
        assert _detect_remote('Fully remote position') == 'remote'

    def test_remote_keyword(self):
        assert _detect_remote('Location: Remote, US') == 'remote'

    def test_hybrid(self):
        assert _detect_remote('Hybrid — 2 days in office') == 'hybrid'

    def test_onsite(self):
        assert _detect_remote('Must work from our NYC office') == 'onsite'

    def test_100_remote(self):
        assert _detect_remote('100% remote') == 'remote'


class TestDetectC2C:
    def test_c2c(self):
        assert _detect_c2c('C2C contract available') is True

    def test_corp_to_corp(self):
        assert _detect_c2c('corp-to-corp only') is True

    def test_w2_c2c(self):
        assert _detect_c2c('W2 or C2C') is True

    def test_1099(self):
        assert _detect_c2c('1099 contractor') is True

    def test_no_c2c(self):
        assert _detect_c2c('Full-time employee only') is False


class TestDetectCompanyStage:
    def test_startup(self):
        assert _detect_company_stage('Series A startup') == 'startup'

    def test_enterprise(self):
        assert _detect_company_stage('Fortune 500 company') == 'enterprise'

    def test_growth(self):
        assert _detect_company_stage('Series C, scaling fast') == 'growth'

    def test_unknown(self):
        assert _detect_company_stage('A company') == 'unknown'


class TestDetectUrgency:
    def test_immediate(self):
        assert _detect_urgency('Start immediately') == 5

    def test_asap(self):
        assert _detect_urgency('Need someone ASAP') == 5

    def test_soon(self):
        assert _detect_urgency('Looking to fill soon') == 3

    def test_no_signal(self):
        assert _detect_urgency('Great opportunity') == 2


# ══════════════════════════════════════════════════════════════
# INDIVIDUAL DIMENSION SCORING
# ══════════════════════════════════════════════════════════════

class TestScoreRoleMatch:
    def test_perfect_match(self):
        matched = {'java', 'spring boot', 'kafka', 'kubernetes', 'microservices',
                   'docker', 'aws', 'graphql', 'mongodb', 'rest'}
        result = score_role_match('Senior Java Backend Microservice API Developer', matched)
        assert result.score >= 4.5
        assert result.weight == 'gate-pass'

    def test_no_match(self):
        result = score_role_match('Data entry clerk', set())
        assert result.score <= 2.0

    def test_partial_match(self):
        matched = {'java', 'spring boot', 'kafka'}
        result = score_role_match('Java developer', matched)
        assert 2.0 <= result.score <= 4.0


class TestScoreSkillsAlignment:
    def test_high_match(self):
        result = score_skills_alignment({'java', 'spring boot', 'kafka'}, {'go'}, 85)
        assert result.score >= 4.5
        assert result.weight == 'gate-pass'

    def test_low_match(self):
        result = score_skills_alignment({'java'}, {'go', 'rust', 'scala', 'haskell'}, 20)
        assert result.score <= 2.5

    def test_medium_match(self):
        result = score_skills_alignment({'java', 'spring boot'}, {'go', 'rust'}, 60)
        assert 3.0 <= result.score <= 4.5

    def test_zero_match(self):
        result = score_skills_alignment(set(), {'go', 'rust'}, 0)
        assert result.score <= 1.5


class TestScoreSeniority:
    def test_exact_match(self):
        result = score_seniority('Senior Java Developer')
        assert result.score == 5.0

    def test_one_above(self):
        result = score_seniority('Lead Engineer')
        assert result.score == 4.0  # stretch up

    def test_one_below(self):
        result = score_seniority('Mid-level developer')
        assert result.score == 3.5

    def test_way_below(self):
        result = score_seniority('Junior entry level')
        assert result.score <= 2.0


class TestScoreCompensation:
    def test_in_range(self):
        result = score_compensation('Rate: $65-80/hr')
        assert result.score >= 4.0

    def test_above_range(self):
        result = score_compensation('Rate: $95-120/hr')
        assert result.score == 5.0

    def test_below_range(self):
        result = score_compensation('Rate: $30-40/hr')
        assert result.score <= 3.0

    def test_no_data(self):
        result = score_compensation('Great opportunity')
        assert result.score == 3.0  # neutral

    def test_structured_data_override(self):
        result = score_compensation('', min_rate=70, max_rate=85, interval='hourly')
        assert result.score >= 4.0

    def test_annual_conversion(self):
        # $140k-180k annual = ~$67-87/hr — should be in range
        result = score_compensation('Salary: $140,000 - $180,000')
        assert result.score >= 3.5


class TestScoreGeographic:
    def test_remote(self):
        result = score_geographic('Fully remote position')
        assert result.score == 5.0

    def test_hybrid_near(self):
        result = score_geographic('Hybrid in Denver, CO')
        assert result.score == 4.0

    def test_hybrid_far(self):
        result = score_geographic('Hybrid in New York')
        assert result.score == 2.5

    def test_onsite_near(self):
        result = score_geographic('Onsite in Colorado')
        assert result.score == 3.5

    def test_onsite_far(self):
        result = score_geographic('Onsite in San Francisco only')
        assert result.score == 1.5


class TestScoreCompanyStage:
    def test_enterprise(self):
        result = score_company_stage('Fortune 500 global company')
        assert result.score == 4.5

    def test_growth(self):
        result = score_company_stage('Series C scaling startup')
        assert result.score == 4.0

    def test_startup(self):
        result = score_company_stage('Early stage seed startup')
        assert result.score == 3.0

    def test_unknown(self):
        result = score_company_stage('A company')
        assert result.score == 3.0


class TestScoreProductMarketFit:
    def test_strong_domain(self):
        result = score_product_market_fit('Telecom SaaS platform with data pipeline')
        assert result.score >= 4.0

    def test_no_domain(self):
        result = score_product_market_fit('A company doing things')
        assert result.score == 2.5

    def test_partial_domain(self):
        result = score_product_market_fit('E-commerce platform')
        assert result.score >= 3.0


class TestScoreGrowthTrajectory:
    def test_strong_growth(self):
        result = score_growth_trajectory('Career growth to Lead and Architect path')
        assert result.score >= 3.5

    def test_no_growth(self):
        result = score_growth_trajectory('Contract role, 6 months')
        assert result.score == 2.0

    def test_mentor(self):
        result = score_growth_trajectory('Mentor junior developers, leadership opportunity')
        assert result.score >= 3.0


class TestScoreInterviewLikelihood:
    def test_high_match_c2c(self):
        result = score_interview_likelihood('C2C green card', 85, True)
        assert result.score >= 4.5

    def test_low_match_no_c2c(self):
        result = score_interview_likelihood('Full time only', 30, False)
        assert result.score <= 3.0

    def test_medium_match_c2c(self):
        result = score_interview_likelihood('C2C available', 65, True)
        assert result.score >= 3.5


class TestScoreTimeline:
    def test_urgent(self):
        result = score_timeline('Start immediately, ASAP')
        assert result.score == 5.0

    def test_normal(self):
        result = score_timeline('Standard hiring process')
        assert result.score == 2.0


# ══════════════════════════════════════════════════════════════
# FINAL SCORE + GRADE CALCULATION
# ══════════════════════════════════════════════════════════════

class TestCalculateFinalScore:
    def test_all_fives(self):
        dims = [DimensionScore('A', 5.0, 'gate-pass'),
                DimensionScore('B', 5.0, 'gate-pass'),
                DimensionScore('C', 5.0, 'high'),
                DimensionScore('D', 5.0, 'medium'),
                DimensionScore('E', 5.0, 'low')]
        score, grade = calculate_final_score(dims)
        assert score == 5.0
        assert grade == 'A'

    def test_all_ones(self):
        dims = [DimensionScore('A', 1.0, 'gate-pass'),
                DimensionScore('B', 1.0, 'high'),
                DimensionScore('C', 1.0, 'medium')]
        score, grade = calculate_final_score(dims)
        assert score == 1.0
        assert grade == 'F'

    def test_gate_pass_failure_caps_score(self):
        """If gate-pass dimension < 2.5, final score capped at 2.5."""
        dims = [DimensionScore('Role', 1.5, 'gate-pass'),  # FAILS gate
                DimensionScore('Skills', 5.0, 'gate-pass'),
                DimensionScore('Comp', 5.0, 'high'),
                DimensionScore('Geo', 5.0, 'medium')]
        score, grade = calculate_final_score(dims)
        assert score <= 2.5

    def test_grade_a(self):
        dims = [DimensionScore('A', 4.8, 'high')]
        score, grade = calculate_final_score(dims)
        assert grade == 'A'

    def test_grade_b(self):
        dims = [DimensionScore('A', 4.2, 'high')]
        score, grade = calculate_final_score(dims)
        assert grade == 'B'

    def test_grade_c(self):
        dims = [DimensionScore('A', 3.5, 'high')]
        score, grade = calculate_final_score(dims)
        assert grade == 'C'

    def test_grade_d(self):
        dims = [DimensionScore('A', 2.5, 'high')]
        score, grade = calculate_final_score(dims)
        assert grade == 'D'

    def test_weights_matter(self):
        """Higher-weight dimensions should influence score more."""
        # All high-weight at 5, low-weight at 1
        dims = [DimensionScore('A', 5.0, 'high'),
                DimensionScore('B', 5.0, 'high'),
                DimensionScore('C', 1.0, 'low')]
        score, _ = calculate_final_score(dims)
        # Should be closer to 5 than to 1
        assert score > 4.0

    def test_empty_dimensions(self):
        score, grade = calculate_final_score([])
        assert score == 1.0  # min clamp
        assert grade == 'F'


class TestGetVerdict:
    def test_strong_match(self):
        v = get_verdict('A', 85, True)
        assert 'STRONG' in v or 'Apply immediately' in v

    def test_good_fit(self):
        v = get_verdict('B', 55, True)
        assert 'GOOD' in v or 'tailor' in v.lower()

    def test_decent(self):
        v = get_verdict('C', 65, True)
        assert 'DECENT' in v or 'Apply if' in v

    def test_skip(self):
        v = get_verdict('D', 30, False)
        assert 'SKIP' in v


# ══════════════════════════════════════════════════════════════
# FULL EVALUATION (end-to-end unit test)
# ══════════════════════════════════════════════════════════════

class TestEvaluateJob:
    def test_perfect_job_scores_high(self):
        result = evaluate_job(PERFECT_JOB, title='Senior Java Backend Developer',
                              company='TechGrowth Solutions')
        assert result.grade in ('A', 'B')
        assert result.final_score >= 4.0
        assert result.match_pct >= 70
        assert len(result.matched_skills) >= 10
        assert 'Apply' in result.verdict or 'STRONG' in result.verdict

    def test_weak_job_scores_low(self):
        result = evaluate_job(WEAK_JOB, title='Data Entry Clerk', company='Unknown')
        assert result.grade in ('D', 'F')
        assert result.final_score <= 2.5
        assert result.match_pct < 30

    def test_medium_job_scores_middle(self):
        result = evaluate_job(MEDIUM_JOB, title='Java Developer', company='Pyramid Consulting')
        # Gate-pass (Role Match) is low because only 3/10 core stack matched
        # This caps the score — correct behavior for a basic Java+SQL job
        assert result.grade in ('C', 'D')
        assert 2.0 <= result.final_score <= 3.5

    def test_no_comp_neutral(self):
        result = evaluate_job(NO_COMP_JOB, title='Senior Java Engineer')
        # Should still score well on skills, neutral on comp
        assert result.match_pct >= 50
        comp_dim = next(d for d in result.dimensions if d.name == 'Compensation')
        assert comp_dim.score == 3.0  # neutral when no data

    def test_all_dimensions_present(self):
        result = evaluate_job(PERFECT_JOB)
        assert len(result.dimensions) == 10
        names = {d.name for d in result.dimensions}
        assert 'Role Match' in names
        assert 'Skills Alignment' in names
        assert 'Seniority' in names
        assert 'Compensation' in names
        assert 'Geographic' in names
        assert 'Company Stage' in names
        assert 'Product-Market Fit' in names
        assert 'Growth Trajectory' in names
        assert 'Interview Likelihood' in names
        assert 'Timeline' in names

    def test_score_bounds(self):
        """All scores must be between 1.0 and 5.0."""
        for job_text in [PERFECT_JOB, WEAK_JOB, MEDIUM_JOB, NO_COMP_JOB, '']:
            result = evaluate_job(job_text)
            assert 1.0 <= result.final_score <= 5.0
            for d in result.dimensions:
                assert 1.0 <= d.score <= 5.0

    def test_structured_rate_data(self):
        result = evaluate_job(NO_COMP_JOB, min_rate=75, max_rate=85, interval='hourly')
        comp_dim = next(d for d in result.dimensions if d.name == 'Compensation')
        assert comp_dim.score >= 4.0  # in target range

    def test_empty_text(self):
        """Should not crash on empty input."""
        result = evaluate_job('')
        assert result.grade in ('D', 'F')
        assert result.final_score >= 1.0

    def test_gate_pass_enforcement(self):
        """If role doesn't match at all, score should be capped."""
        result = evaluate_job(WEAK_JOB)
        # Role Match and Skills Alignment should both be low → gate-pass fails
        role_dim = next(d for d in result.dimensions if d.name == 'Role Match')
        skills_dim = next(d for d in result.dimensions if d.name == 'Skills Alignment')
        if role_dim.score < 2.5 or skills_dim.score < 2.5:
            assert result.final_score <= 2.5


class TestFormatEvaluation:
    def test_format_not_empty(self):
        result = evaluate_job(PERFECT_JOB, title='Test', company='TestCo')
        output = format_evaluation(result, title='Test', company='TestCo')
        assert 'Test' in output
        assert 'TestCo' in output
        assert 'Role Match' in output
        assert '/5' in output

    def test_format_contains_verdict(self):
        result = evaluate_job(PERFECT_JOB)
        output = format_evaluation(result)
        assert result.verdict in output


# ══════════════════════════════════════════════════════════════
# EDGE CASES
# ══════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_unicode_text(self):
        result = evaluate_job('Java développeur — Spring Boot, Kafka, résumé required')
        assert result.final_score >= 1.0

    def test_very_long_text(self):
        long_text = 'Java Spring Boot Kafka ' * 1000
        result = evaluate_job(long_text)
        assert result.final_score >= 1.0

    def test_special_characters(self):
        result = evaluate_job('Java/Spring Boot (Kafka) [Kubernetes] {Docker} $75-85/hr C2C!!!')
        assert result.match_pct > 0

    def test_case_insensitive(self):
        result1 = evaluate_job('JAVA SPRING BOOT KAFKA')
        result2 = evaluate_job('java spring boot kafka')
        # Should produce similar results
        assert abs(result1.match_pct - result2.match_pct) <= 10

    def test_none_values_dont_crash(self):
        """Passing None-like values shouldn't crash."""
        result = evaluate_job('Java developer', title='', company='',
                              min_rate=0, max_rate=0, interval='')
        assert result.final_score >= 1.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
