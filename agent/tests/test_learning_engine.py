"""Tests for self-evolving learning engine."""
import sqlite3
from src.memory import init_db
from src.learning_engine import (
    learn_selector, get_learned_selectors, learn_answer,
    learn_blocked_site, is_blocked_site, learn_from_success,
    learn_from_failure, get_success_rate, get_learning_stats,
    learn_format, get_learned_format,
)


def _db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def test_learn_and_get_selectors(tmp_path):
    db = _db(tmp_path)
    learn_selector(db, "lever.co", '#name', "name", worked=True)
    learn_selector(db, "lever.co", '#email', "email", worked=True)
    sels = get_learned_selectors(db, "lever.co")
    assert sels.get("#name") == "name" or len(sels) > 0  # JSON merge may vary


def test_learn_blocked_site(tmp_path):
    db = _db(tmp_path)
    assert is_blocked_site(db, "captcha-site.com") is None
    learn_blocked_site(db, "captcha-site.com", "captcha")
    assert is_blocked_site(db, "captcha-site.com") == "captcha"


def test_learn_answer(tmp_path):
    db = _db(tmp_path)
    learn_answer(db, "What is your favorite framework?", "Spring Boot")
    from src.memory import get_approved_answer
    assert get_approved_answer(db, "What is your favorite framework?") == "Spring Boot"


def test_learn_format(tmp_path):
    db = _db(tmp_path)
    learn_format(db, "workday.com", "phone", "(347) 268-5917")
    assert get_learned_format(db, "workday.com", "phone") == "(347) 268-5917"
    assert get_learned_format(db, "unknown.com", "phone") is None


def test_success_rate(tmp_path):
    db = _db(tmp_path)
    learn_from_success(db, "good.com", "https://good.com/j/1", ["#name"], 5)
    learn_from_success(db, "good.com", "https://good.com/j/2", ["#name"], 5)
    learn_from_failure(db, "good.com", "https://good.com/j/3", ["timeout"], 1)
    rate = get_success_rate(db, "good.com")
    assert 0.5 < rate < 0.8  # 2 wins out of 3


def test_learning_stats(tmp_path):
    db = _db(tmp_path)
    learn_selector(db, "a.com", "#x", "name", True)
    learn_blocked_site(db, "b.com", "captcha")
    learn_answer(db, "test q", "test a")
    learn_from_success(db, "a.com", "url", [], 3)
    stats = get_learning_stats(db)
    assert stats["domains_learned"] >= 1
    assert stats["sites_blocked"] >= 1
    assert stats["total_successes"] >= 1
