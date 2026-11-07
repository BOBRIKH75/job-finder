import linkedin_pw_apply as m

P = {"years_experience": 10, "requires_sponsorship": False, "work_authorization": True,
     "skills": ["java", "spring boot"], "rate_target": 75, "first_name": "A"}


def test_sponsorship_no():
    assert m.answer_for("Will you require visa sponsorship?", P) == "No"


def test_authorized_yes():
    assert m.answer_for("Are you legally authorized to work in the US?", P) == "Yes"


def test_known_skill_years():
    assert m.answer_for("How many years of work experience do you have with Java?", P) == "10"


def test_unknown_skill_returns_zero():
    assert m.answer_for("How many years of experience with COBOL?", P) == "0"


def test_typo_years_known_skill():
    assert m.answer_for("How many years expereince with Java and Spring Boot do you have?", P) == "10"


def test_hear_about():
    assert m.answer_for("How did you first hear about this job?", P) == "LinkedIn"


def test_address_line_unknown():
    assert m.answer_for("Address Line 1*", P) is None


def test_unknown_question_none():
    assert m.answer_for("Favorite color?", P) is None


def test_phone_type_and_state():
    p = dict(P, state="CO")
    assert m.answer_for("Type*", p) == "Mobile"
    assert m.answer_for("State or Province*", p) == "CO"
    assert m.answer_for("Secondary Phone Number", p) is None
