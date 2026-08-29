"""Tests for recruiter auto-reply deliverability guard.

Ensures the agent replies ONLY to real humans writing to Bob — never to
job-board alerts, newsletters, no-reply, role addresses, or cold inbound.
Protects Gmail sender reputation so real recruiter mail doesn't land in spam.
"""
import os
import sys
import email

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import recruiter_auto_reply as r


def _msg(from_addr, subject="", in_reply_to=None, references=None):
    m = email.message.EmailMessage()
    m["From"] = from_addr
    m["Subject"] = subject
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
    if references:
        m["References"] = references
    return m


CONTACTED = {"sarah.recruiter@beaconhill.com"}


# --- Blocked: job boards / platforms ---
def test_block_linkedin_alerts():
    ok, _ = r._should_reply_to("jobalerts-noreply@linkedin.com", _msg("x@linkedin.com"), CONTACTED)
    assert ok is False


def test_block_indeed():
    ok, _ = r._should_reply_to("alerts@indeedemail.com", _msg("x@indeedemail.com"), CONTACTED)
    assert ok is False


def test_block_dice_noreply():
    ok, _ = r._should_reply_to("no-reply@dice.com", _msg("x@dice.com"), CONTACTED)
    assert ok is False


def test_block_newsletter_domain():
    ok, _ = r._should_reply_to("digest@medium.com", _msg("x@medium.com"), CONTACTED)
    assert ok is False


# --- Blocked: role / automated local-parts ---
def test_block_jobs_role_address():
    ok, _ = r._should_reply_to("jobs@bigco.com", _msg("jobs@bigco.com"), CONTACTED)
    assert ok is False


def test_block_alerts_at_real_company():
    ok, _ = r._should_reply_to("alerts@apexsystems.com", _msg("alerts@apexsystems.com"), CONTACTED)
    assert ok is False


# --- Blocked: cold inbound stranger (not a reply, not known) ---
def test_block_cold_inbound_person():
    ok, _ = r._should_reply_to("mike.new@somestaffing.com", _msg("mike.new@somestaffing.com", "Java opp"), CONTACTED)
    assert ok is False


# --- Allowed: real recruiter replying to Bob ---
def test_allow_reply_to_bob_via_header():
    ok, reason = r._should_reply_to(
        "Sarah Johnson <sarah.johnson@apexsystems.com>",
        _msg("sarah.johnson@apexsystems.com", "Re: Java C2C", in_reply_to="<abc@mail>"),
        CONTACTED,
    )
    assert ok is True


def test_allow_reply_to_bob_via_subject():
    ok, _ = r._should_reply_to(
        "Sarah Johnson <sarah.johnson@apexsystems.com>",
        _msg("sarah.johnson@apexsystems.com", "Re: your application"),
        CONTACTED,
    )
    assert ok is True


# --- Allowed: known contacted recruiter (fresh subject) ---
def test_allow_known_contacted_recruiter():
    ok, _ = r._should_reply_to(
        "Sarah Recruiter <sarah.recruiter@beaconhill.com>",
        _msg("sarah.recruiter@beaconhill.com", "Following up on Java role"),
        CONTACTED,
    )
    assert ok is True


# --- Real company domain must NOT be false-blocked by generic words ---
def test_company_with_system_in_name_not_blocked():
    # "apexsystems.com" must not trip the 'system' automated-word filter
    ok, _ = r._should_reply_to(
        "John Doe <john.doe@apexsystems.com>",
        _msg("john.doe@apexsystems.com", "Re: role", in_reply_to="<x@y>"),
        CONTACTED,
    )
    assert ok is True


def test_person_email_helper():
    assert r._looks_like_person_email("sarah.johnson") is True
    assert r._looks_like_person_email("jobs") is False
    assert r._looks_like_person_email("noreply") is False
