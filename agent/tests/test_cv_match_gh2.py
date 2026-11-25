"""CV matcher: loosened for real Java/backend lanes, still strict on wrong stacks/roles."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.cv_match import should_apply  # noqa: E402


def test_java_in_title_passes():
    assert should_apply("Senior Java Engineer - Core/Infra", "java services", "")[0]


def test_backend_title_with_thin_jd_passes():
    assert should_apply("Software Engineer - Backend Networking", "backend", "")[0]


def test_generic_se_with_stack_rich_jd_passes():
    jd = "microservices on kafka and kubernetes in aws"
    assert should_apply("Senior Software Engineer", jd, "")[0]


def test_generic_se_frontend_jd_rejected():
    assert not should_apply("Senior Software Engineer", "react frontend css", "")[0]


def test_other_language_title_rejected():
    assert not should_apply("Backend Engineer, Repository Services (Ruby)", "ruby java", "")[0]
    assert not should_apply("Python Engineer", "java spring", "")[0]


def test_security_and_sales_roles_rejected():
    assert not should_apply("Staff Security Engineer", "backend", "")[0]
    assert not should_apply("Sr. Solutions Engineer", "java", "")[0]


def test_non_engineering_title_rejected():
    assert not should_apply("Operations Associate", "java spring backend microservices kafka", "")[0]


def test_senior_ic_titles_allowed_manager_titles_skipped():
    for t in ("Lead Java Developer", "Java Architect", "Principal Java Engineer",
              "Java Tech Lead - Remote", "Staff Backend Engineer (Java)", "Senior Java Developer - 10+ Years"):
        assert should_apply(t, "java spring boot kafka", "Remote")[0], t
    assert not should_apply("Director of Java Platform", "java spring boot", "Remote")[0]


def test_years_requirement_gate_follows_profile():
    assert not should_apply("Java Developer", "Requires 15+ years of Java and Spring", "Remote")[0]
    assert not should_apply("Java Developer - 20+ Years", "java spring", "Remote")[0]
    assert should_apply("Sr Java Developer", "10+ years Java, Spring Boot, Kafka", "Remote")[0]


def test_title_onsite_outside_colorado_skipped_even_if_location_remote():
    assert not should_apply("Sr AWS Java Developer (Onsite Plano, TX)", "java spring aws", "Remote")[0]
    assert not should_apply("Senior Java Developer - Local to Michigan", "java spring", "Remote")[0]
    assert should_apply("Java software developers - Denver Metropolitan only", "java spring", "Remote")[0]
    assert should_apply("Java Developer (Hybrid Denver, CO)", "java spring", "Remote")[0]


def test_allow_senior_override(monkeypatch):
    monkeypatch.setenv("CV_ALLOW_SENIOR", "1")
    assert should_apply("Java Developer", "Requires 15+ years of Java", "Remote")[0]
