import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.greenhouse_api import _answer_question

PROFILE = json.load(open(os.path.join(os.path.dirname(__file__), "..", "config", "profile.json")))


def q(label, options=None, required=True, ftype="multi_value_single_select"):
    vals = [{"label": o, "value": i + 1} for i, o in enumerate(options or [])]
    return {"label": label, "required": required, "fields": [{"name": "f", "type": ftype, "values": vals}]}


def pick(label, options, required=True):
    v = _answer_question(q(label, options, required), PROFILE)
    return None if v is None else options[int(v) - 1]


def test_sponsorship_never_yes_even_when_yes_option_says_now():
    opts = ["Yes, I will require sponsorship now or in the future", "No, I will not require sponsorship"]
    assert pick("Will you now or in the future require visa sponsorship?", opts) == opts[1]


def test_authorized_yes():
    assert pick("Are you legally authorized to work in the United States?", ["Yes", "No"]) == "Yes"


def test_knockout_yes_questions():
    for label in ("Are you at least 18 years of age?", "Are you 18 years of age or older?",
                  "Do you consent to a background check?", "I agree to the privacy policy",
                  "I certify that the information provided is accurate"):
        assert pick(label, ["Yes", "No"]) == "Yes", label


def test_eeo_declines_and_never_invents():
    assert pick("Veteran status", ["I am a protected veteran", "I am not a protected veteran",
                                   "I don't wish to answer"]) == "I don't wish to answer"
    assert pick("Disability status", ["Yes, I have a disability", "No, I don't have a disability",
                                      "I do not want to answer"]) == "I do not want to answer"
    assert pick("Gender", ["Male", "Female", "Decline to self-identify"]) == "Decline to self-identify"
    assert pick("Veteran status", ["I am a protected veteran", "I am not a protected veteran"]) is None


def test_country_and_state_pickers():
    assert pick("Country", ["Canada", "United States", "Mexico"]) == "United States"
    states = ["Alabama", "Arizona", "California", "Colorado", "Florida", "Georgia", "Illinois",
              "New York", "Ohio", "Texas", "Utah", "Washington"]
    assert pick("Which state do you reside in?", states) == "Colorado"
    assert pick("Do you currently reside in the United States?", ["Yes", "No"]) == "Yes"


def test_unknown_required_left_empty_not_no():
    assert pick("Have you used our product Zorblax in production?", ["Option A", "Option B"]) is None


def test_onsite_outside_colorado_is_truthful_no():
    assert pick("Are you willing to work onsite in San Jose, CA 5 days a week?", ["Yes", "No"]) == "No"


def test_salary_text_is_annual_and_corporate_is_not_rate():
    s = _answer_question(q("Desired annual salary", ftype="input_text"), PROFILE)
    assert int(s) >= 100000
    assert _answer_question(q("Corporate email of your manager", ftype="input_text"), PROFILE) != str(PROFILE["rate_target"])
    assert _answer_question(q("Desired hourly rate", ftype="input_text"), PROFILE) == str(PROFILE["rate_target"])
