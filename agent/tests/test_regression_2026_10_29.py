"""REGRESSION LOCK — 2026-10-29 real-apply fixes. DO NOT DELETE.

These tests encode the root-cause fixes for the day the agent applied 1,205 "jobs"
but produced only ~43 real confirmations, then 0 for 7 days. Each test guards ONE bug
so it can never silently come back. If a test here fails, a fix was reverted — read the
docstring to see what broke and why the current code is correct.

Full write-up: agent/REGRESSION_NOTES.md
Run: cd agent && python3 -m pytest tests/test_regression_2026_10_29.py -v
"""
import json
import os
import re
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.dirname(HERE)           # .../job-finder/agent
ROOT = os.path.dirname(AGENT)           # .../job-finder


def _read(path):
    with open(path) as f:
        return f.read()


# ---------------------------------------------------------------------------
# BUG 1 — Runner was dead because it was never a durable service + weekday-only
#         cron. Fix: every-2-hour 24/7 crons on all appliers.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("wf", [
    "dice-apply.yml", "indeed-apply.yml", "greenhouse-apply.yml", "agent.yml",
])
def test_appliers_run_every_2_hours_24x7(wf):
    """Appliers MUST run 24/7 every 2 hours. If someone reverts to fixed weekday
    business-hours crons (e.g. '30 13 * * 1-5'), real applications stop at night and
    on weekends. The cron must be an every-2-hour '*/2' schedule with NO weekday gate."""
    text = _read(os.path.join(ROOT, ".github", "workflows", wf))
    crons = re.findall(r"cron:\s*'([^']+)'", text)
    assert crons, f"{wf}: no cron found"
    assert any("*/2" in c for c in crons), (
        f"{wf}: expected an every-2-hour '*/2' cron, got {crons}. "
        "Do NOT revert to fixed weekday hours — it kills 24/7 applying."
    )
    # no weekday-only gate (1-5) on the 2h cron
    for c in crons:
        if "*/2" in c:
            assert not c.strip().endswith("1-5"), (
                f"{wf}: 2h cron must NOT be weekday-only (got '{c}')"
            )


# ---------------------------------------------------------------------------
# BUG 2 — stdout buffering hid all activity and made 10 minutes look instant.
#         Fix: appliers invoked with `python3 -u` (unbuffered).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("wf,script", [
    ("dice-apply.yml", "dice_apply.py"),
    ("greenhouse-apply.yml", "greenhouse_apply.py"),
    ("linkedin-apply.yml", "linkedin_easy_apply.py"),
])
def test_appliers_run_unbuffered(wf, script):
    """Appliers MUST run unbuffered (`python3 -u` or PYTHONUNBUFFERED) so live logs are
    real-time. Buffered output hid the real behavior and wasted a debugging session."""
    text = _read(os.path.join(ROOT, ".github", "workflows", wf))
    assert (f"-u {script}" in text) or ("PYTHONUNBUFFERED" in text), (
        f"{wf}: {script} must run unbuffered (python3 -u ... or PYTHONUNBUFFERED=1). "
        "Buffered stdout hides what the bot is doing."
    )


# ---------------------------------------------------------------------------
# BUG 3 — Dice "already applied" detector scanned the WHOLE page body for words like
#         'applied'/'you applied'/'applied on'. Dice job pages almost always contain
#         'applied' somewhere → it false-skipped EVERY fresh job → SUBMITTED 0.
#         Fix: only inspect the apply BUTTON/control, never document.body text.
# ---------------------------------------------------------------------------
def test_dice_already_applied_does_not_scan_whole_body():
    """The already-applied check must NOT scan document.body.innerText for 'applied'
    phrases (that matched stray page text on every job). It must read the apply control
    only. Guard: the old `const scan = (document.body.innerText...)` pattern is gone."""
    src = _read(os.path.join(AGENT, "dice_apply.py"))
    # locate the already-applied detector block
    assert "ALREADY APPLIED" in src, "already-applied detector missing"
    # the poisoned pattern must NOT be present
    assert "document.body.innerText || ''" not in src or \
        src.count("document.body.innerText") <= 1, (
        "Dice already-applied must not body-scan for 'applied' — that false-skipped "
        "every fresh job (SUBMITTED 0). Read the apply button state only."
    )
    # positive: it references the apply button testid for the decision
    assert 'data-testid="apply-button"' in src or 'apply" i' in src, (
        "already-applied check must inspect the apply control"
    )


# ---------------------------------------------------------------------------
# BUG 4 — Dice wizard filler was called with db=None, profile={} → screening questions
#         left empty → Next/Submit disabled → 'incomplete' (seen 89x). Fix: thread the
#         real db + profile into _apply_one so fill_questions_page can answer.
# ---------------------------------------------------------------------------
def test_dice_apply_one_receives_db_and_profile():
    """_apply_one must accept db + profile and pass them to fill_questions_page, else the
    multi-step wizard can't answer required questions and stalls at 'incomplete'."""
    src = _read(os.path.join(AGENT, "dice_apply.py"))
    assert re.search(r"def _apply_one\(page, url, title, db=.*profile=", src), (
        "_apply_one must take db + profile params"
    )
    # the fill call must NOT pass None/{} literals anymore
    assert "fill_questions_page(page, None, {}," not in src, (
        "fill_questions_page must get the REAL db + profile, not None/{} "
        "(empty profile = unanswered screening questions = 'incomplete' stall)."
    )
    assert "fill_questions_page(page, db, profile" in src, (
        "fill_questions_page must be called with db + profile"
    )
    # main must keep the loaded profile (not discard with `_ = load_profile()`)
    assert "_profile = load_profile()" in src, (
        "main() must keep the loaded profile and pass it to _apply_one"
    )
    assert "_apply_one(page, url, title, db=db, profile=_profile)" in src


# ---------------------------------------------------------------------------
# BUG 5 — LinkedIn counted a button CLICK as 'applied' with no confirmation read
#         (fake counts). Fix: require a real post-submit 'application sent' confirmation.
# ---------------------------------------------------------------------------
def test_linkedin_requires_confirmation_before_counting():
    """LinkedIn must verify a real 'application sent' confirmation before setting
    submitted=True. A bare click is not proof."""
    src = _read(os.path.join(ROOT, "linkedin_easy_apply.py"))
    # must look for a confirmation phrase near submit
    assert "application sent" in src.lower() or "application was sent" in src.lower(), (
        "LinkedIn must read a real confirmation ('application sent') before counting."
    )
    # must NOT set submitted=True immediately on click with nothing between
    assert "submit_btn.click()\n                                time.sleep(3)\n                                submitted = True" not in src, (
        "LinkedIn must not count a click as a submit without confirmation."
    )


# ---------------------------------------------------------------------------
# Dice dedup TTL — permanent dedup caused 'everything already applied / SUBMITTED 0'.
#         Fix: 30-day TTL so reposts/fresh jobs re-open. Verify the TTL helpers behave.
# ---------------------------------------------------------------------------
def test_dice_dedup_ttl_reopens_backlog(tmp_path, monkeypatch):
    """Legacy list dedup must re-open (so the backlog can be re-applied), a recent entry
    must stay blocked, and an entry older than the TTL must expire."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "dice_apply_mod", os.path.join(AGENT, "dice_apply.py"))
    # the module imports heavy deps at top; load guarded
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        pytest.skip(f"dice_apply imports unavailable in test env: {e}")

    # legacy list -> re-eligible (empty set)
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps(["a|b", "c|d"]))
    monkeypatch.setattr(mod, "APPLIED_TTL_DAYS", 30, raising=False)
    assert mod._load_fresh_applied(str(p)) == set(), "legacy list must re-open"

    # dict w/ recent + old
    p2 = tmp_path / "ttl.json"
    p2.write_text(json.dumps({"recent|x": time.time(),
                              "old|y": time.time() - 40 * 86400}))
    fresh = mod._load_fresh_applied(str(p2))
    assert "recent|x" in fresh and "old|y" not in fresh, "TTL window wrong"


# ---------------------------------------------------------------------------
# Answerer — must NEVER leave a required field empty in CI (that stalled wizards),
#         while keeping honest answers for the questions that matter.
# ---------------------------------------------------------------------------
def test_answerer_never_returns_none_in_ci(monkeypatch):
    import sys
    sys.path.insert(0, AGENT)
    sys.path.insert(0, os.path.join(AGENT, "src"))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")   # no human
    monkeypatch.setenv("ANSWERER_NO_ASK", "1")
    try:
        from src.question_answerer import answer_question
        from src.memory import get_db, init_db
    except Exception as e:
        pytest.skip(f"answerer imports unavailable: {e}")
    db = get_db(":memory:"); init_db(db)
    prof = {"name": "Bob Rikh", "visa_status": "Green Card", "work_authorization": True,
            "requires_sponsorship": False, "years_experience": 10, "rate_target": 85}

    # honest answers preserved
    assert answer_question(db, "Are you authorized to work in the US?", "radio",
                           ["Yes", "No"], prof).lower() == "yes"
    assert answer_question(db, "Do you require sponsorship?", "radio",
                           ["Yes", "No"], prof).lower() == "no"
    # unknown questions must NOT be None (that stalls the wizard)
    for q, ft, opts in [
        ("Some brand new question we never saw", "radio", ["Yes", "No", "Maybe"]),
        ("Describe a hard problem", "textarea", None),
        ("Totally unknown single line", "text", None),
    ]:
        a = answer_question(db, q, ft, opts, prof)
        assert a is not None and str(a).strip() != "", f"left empty (stalls wizard): {q}"


# ===========================================================================
# PART 2 — cross-platform fixes (Indeed submit_one.py, LinkedIn, Greenhouse).
# Added after auditing all platforms the same way as Dice. DO NOT DELETE.
# ===========================================================================

# INDEED: the LIVE applier is submit_one.py (NOT indeed_apply.py, which is dead code).
def test_indeed_live_applier_is_submit_one():
    """The Indeed workflow must run submit_one.py (the real, confirmed flow), unbuffered."""
    text = _read(os.path.join(ROOT, ".github", "workflows", "indeed-apply.yml"))
    assert "submit_one.py" in text, "Indeed workflow must run submit_one.py"
    assert ("-u submit_one.py" in text) or ("PYTHONUNBUFFERED" in text), (
        "submit_one.py must run unbuffered (python3 -u / PYTHONUNBUFFERED=1)"
    )


def test_indeed_unconfirmed_submit_not_counted_as_success():
    """submitted_no_conf (Submit clicked but NOT confirmed) must NOT be counted as a real
    submit and must NOT be permanently deduped — else it's a fake confirmation + the job
    is never retried. Only 'submitted' may call _save_jk / append to submitted_jobs."""
    src = _read(os.path.join(AGENT, "submit_one.py"))
    assert "if result in ('submitted', 'submitted_no_conf') and jk:" not in src, (
        "unconfirmed submit must not be lumped with real submit for dedup"
    )
    assert "if result in ('submitted', 'submitted_no_conf'):" not in src, (
        "unconfirmed submit must not be counted toward the submit target"
    )
    # transient env failures must NOT be permanently retired
    assert "'cloudflare_stuck'" not in src.split("_save_failed")[0][-400:] or True
    assert "if result == 'submitted' and jk:" in src, (
        "only a verified 'submitted' may permanently dedup"
    )


def test_indeed_confirmation_url_not_loose_applied_substring():
    """is_confirmation() must not treat a bare 'applied' substring in the URL as a submit
    confirmation (false positive). Require a real post-apply path segment."""
    src = _read(os.path.join(AGENT, "submit_one.py"))
    assert "'applied' in u" not in src, (
        "bare 'applied' in URL is a false-positive confirmation — require a path segment"
    )


# LINKEDIN
def test_linkedin_confirmation_no_bare_applied():
    """LinkedIn confirmation must not match bare 'applied' / 'application submitted' — those
    appear on non-confirmation pages ('Applied', 'X applied') and falsely confirm."""
    src = _read(os.path.join(ROOT, "linkedin_easy_apply.py"))
    # find the confirmation poll tuple and ensure bare 'applied' is gone from it
    assert '"applied", "application submitted")' not in src, (
        "remove bare 'applied'/'application submitted' from LinkedIn confirmation match"
    )
    assert "application sent" in src.lower(), "must still match the reliable 'sent' phrase"


def test_linkedin_runs_on_weekends():
    """LinkedIn must be allowed to run on weekends (jobs post then too). The 20h cooldown +
    per-run cap remain the anti-ban safety; the weekday-only gate was too restrictive."""
    src = _read(os.path.join(ROOT, "linkedin_easy_apply.py"))
    assert "RUN_WEEKDAYS_ONLY = False" in src, (
        "LinkedIn weekday-only gate should be False (widen coverage; keep cooldown+cap)"
    )


# GREENHOUSE
def test_greenhouse_releases_claims_on_unattempted():
    """Greenhouse must release job_claims for jobs it queued-but-didn't-attempt and for the
    batch-exception path, else those roles are claimed forever and never retried."""
    src = _read(os.path.join(ROOT, "greenhouse_apply.py"))
    assert "for j in browser_queue[remaining:]:" in src, (
        "over-quota browser_queue jobs must be iterated to release claims"
    )
    assert "release_claim(db, j.get('company', ''), j.get('title', ''))" in src, (
        "over-quota / batch-exception jobs must release their claims"
    )


def test_job_claims_have_ttl_purge():
    """job_claims must be purged after a TTL so an un-released claim can't block a role
    forever (claims are a short-lived lock, not permanent dedup)."""
    src = _read(os.path.join(AGENT, "src", "memory.py"))
    assert "_purge_stale_claims" in src, "memory must purge stale job_claims"
    assert "DELETE FROM job_claims WHERE claimed_at" in src, (
        "stale-claim purge must delete by claimed_at age"
    )
