import email, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.mail_guard import is_automated, is_role_mailbox, is_sensitive_mailbox, may_auto_reply

ACCOM = ("Thank you for contacting the Capital One Recruiting Accommodations team! We offer "
         "reasonable accommodations ... If you are requesting an accommodation for an upcoming interview")


def test_capital_one_accommodation_autoreply_is_automated():
    assert is_automated(None, "Re: Full-stack Engineer 4", ACCOM)


def test_accommodation_mailbox_is_sensitive_and_blocked():
    assert is_sensitive_mailbox("recruitingaccommodation@capitalone.com")
    ok, why = may_auto_reply("recruitingaccommodation@capitalone.com", None, "Re: x", "hi")
    assert not ok


def test_auto_submitted_header_is_automated():
    m = email.message_from_string("Auto-Submitted: auto-replied\nSubject: Re: hi\n\nLet's schedule an interview")
    assert is_automated(m, "Re: hi", "Let's schedule an interview")


def test_real_recruiter_reply_is_allowed():
    ok, _ = may_auto_reply("jane.doe@staffingco.com", None, "Re: Java role",
                           "Hi Bob, can we schedule a call tomorrow to discuss the Java role?")
    assert ok


def test_role_mailboxes():
    for a in ("careers@x.com", "jobs@x.com", "noreply@x.com", "talent.team@x.com"):
        assert is_role_mailbox(a)
    assert not is_role_mailbox("jane.doe@x.com")


def test_hr_helpdesk_domain_blocked():
    from src.mail_guard import is_blocked_domain
    assert is_blocked_domain("casehelp@hrhelp.target.com")
    assert not is_blocked_domain("jane@staffingco.com")


def test_outreach_blocks_sensitive(monkeypatch):
    import importlib, sys as _s, os as _o
    root = _o.path.abspath(_o.path.join(_o.path.dirname(__file__), "..", ".."))
    _s.path.insert(0, root)
    o = importlib.import_module("outreach")
    sent = []
    monkeypatch.setattr(o, "_send_via_smtp", lambda *a, **k: sent.append(a) or True, raising=False)
    monkeypatch.setattr(o, "_send_via_resend", lambda *a, **k: sent.append(a) or True, raising=False)
    assert o.send_outreach("recruitingaccommodation@capitalone.com", "s", "<p>x</p>") is False
    assert o.send_outreach("x@hrhelp.target.com", "s", "<p>x</p>") is False
    assert not sent
