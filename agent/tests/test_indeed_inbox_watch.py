import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from indeed_inbox_watch import parse_inbox, classify

SAMPLE = """Messages
Online
Inbox
\xa0
Advanced Image Inc.
Nov 22
Hi There, Thankyou for applying on indeed. Please complete the application process here: https://www
Recruiter A Co
Nov 19
can we setup time for interview?
Awaiting response
Pplied LLC
Nov 19
Hi Bob Rikh,, Thank you for applying for our Full Stack Developer position. We've sent you an email
United Career Networks
Nov 14
?
Proactive Logic Consulting Inc
Aug 24
Sgn Global Technologies
Aug 5
Hi Bob, Thanks for your application. What is your total experience as Full stack Java developer?
Recruiter B
Jul 24, 2024
Bob Rikh saw your message and is interested in the position.
Welcome to Messages
"""


def test_parse_inbox_all_rows():
    items = parse_inbox(SAMPLE)
    assert [m["sender"] for m in items] == [
        "Advanced Image Inc.", "Recruiter A Co", "Pplied LLC", "United Career Networks",
        "Proactive Logic Consulting Inc", "Sgn Global Technologies", "Recruiter B"]
    assert items[1]["awaiting"] is True and items[1]["snippet"] == "can we setup time for interview?"
    assert items[4]["snippet"] == ""


def test_classify_human_vs_auto():
    kinds = {m["sender"]: classify(m["snippet"], m["awaiting"]) for m in parse_inbox(SAMPLE)}
    assert kinds["Recruiter A Co"] == "human"
    assert kinds["United Career Networks"] == "human"
    assert kinds["Sgn Global Technologies"] == "human"
    assert kinds["Advanced Image Inc."] == "auto"
    assert kinds["Pplied LLC"] == "auto"
    assert kinds["Recruiter B"] == "auto"
