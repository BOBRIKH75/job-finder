"""CV matcher: loosened for real Java/backend lanes, still strict on wrong stacks/roles."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.cv_match import should_apply  # noqa: E402


def test_java_in_title_passes():
    assert should_apply("Senior Java Engineer - Core/Infra", "java services", "")[0]


def test_backend_title_with_thin_jd_passes():
    assert should_apply("Staff Software Engineer - Backend Networking", "backend", "")[0]


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
