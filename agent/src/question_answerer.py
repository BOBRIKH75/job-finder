"""Self-learning question answerer for job-application forms.

Answer flow (deterministic, no external LLM required):
  1. MEMORY   — get_approved_answer(db, question): answered before? reuse instantly.
  2. PROFILE  — rule-based answer from config/profile.json (work auth, experience,
                state, salary, education, "why work here", start date, etc.).
  3. ASK USER — if we still don't know, ask the user on the console; save the
                answer to memory so it is reused forever.

Every answer produced by PROFILE or ASK USER is written back to memory via
save_approved_answer, so the agent keeps learning.

Usage:
    from src.question_answerer import answer_question
    ans = answer_question(db, "How many years of Java experience do you have?",
                          field_type="text", options=None, profile=profile)
    # field_type in {"text", "textarea", "radio", "select"}
    # options = list of choice labels for radio/select (helps pick the best match)
"""
from __future__ import annotations

import os
import re
import sys

try:
    from src.memory import get_approved_answer, save_approved_answer
except Exception:  # allow import when run from agent/ root
    from memory import get_approved_answer, save_approved_answer


# Whether we are allowed to prompt the user (interactive local run).
# In CI/headless there is no human, so we skip the prompt and return None.
def _can_ask_user() -> bool:
    if os.environ.get("ANSWERER_NO_ASK", "0") == "1":
        return False
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return False
    return sys.stdin is not None and sys.stdin.isatty()


# --- Profile-based rule answers ---

def _has_word(text: str, *words) -> bool:
    """Whole-word (token) match. Prevents short keywords like 'rate'/'pay'/'amount'
    from false-matching inside longer words ('sepaRATEly', 'incorpoRATEd', 'comPAYny').
    Multi-word phrases (containing a space) fall back to plain substring match.
    """
    for w in words:
        w = w.lower()
        if " " in w:
            if w in text:
                return True
        elif re.search(r"\b" + re.escape(w) + r"\b", text):
            return True
    return False


def _profile_answer(question: str, field_type: str, options, profile: dict):
    """Return an answer from the profile, or None if no rule matches."""
    q = question.lower()
    opts = [str(o) for o in (options or [])]

    # E-SIGNATURE box: "type your name to electronically sign" -> full name.
    if any(k in q for k in ["signature", "type your name", "typing your name",
                            "electronically sign", "sign this form", "e-sign", "your full name"]):
        name = profile.get("name") or f"{profile.get('first_name','')} {profile.get('last_name','')}".strip()
        return name or "Bob Rikh"

    def pick_option(*preferred):
        """Pick the first option matching any preferred keyword."""
        for want in preferred:
            for o in opts:
                if want.lower() in o.lower():
                    return o
        return None

    # --- EEO / demographic questions: always decline to self-identify ---
    opts_blob = " ".join(opts).lower()
    # Attestation / e-signature certification (LEARNED 2026-09-01 from Constellation West/IRS job):
    # "I certify ... true to the best of my knowledge ... Yes, I agree to sign electronically." -> agree.
    if any(k in q for k in ["i certify", "i agree to sign", "sign electronically", "self attestation",
                            "attestation", "electronic signature", "accurate, complete and true",
                            "certify that i have read"]):
        return pick_option("yes, i agree", "i agree", "agree", "yes") or "Yes, I agree to sign electronically."
    # AI resume-review opt-out (LEARNED 2026-09-01): Bob does NOT opt out -> answer "No".
    # The employer disclaimer text is long and may say "comparison"/"algorithm" instead of "review".
    if "opt out" in q or "opt-out" in q or "artificial intelligence" in q \
            or "profile relevancy" in q or ("ai " in q and "resume" in q):
        return pick_option("no") or "No"
    is_race_opts = any(k in opts_blob for k in ["hispanic or latino", "not hispanic or latino",
                                                "african american", "pacific islander", "two or more races"])
    is_disability_opts = "disability" in opts_blob
    is_veteran_opts = "veteran" in opts_blob
    if any(k in q for k in ["gender", "sex "]) or q.strip() == "sex":
        return pick_option("decline", "do not wish", "prefer not") or "Decline to self-identify"
    if "protected veteran" in q or (is_veteran_opts and "protected" in opts_blob):
        return (pick_option("decline", "do not wish", "not a protected veteran")
                or "I decline to self-identify for protected veteran status")
    if "veteran" in q or is_veteran_opts:
        return pick_option("not a veteran", "not a protected", "decline", "do not wish") or "I am not a veteran"
    if "disability" in q or "disabled" in q or is_disability_opts:
        return (pick_option("do not wish", "decline", "not to answer", "don't wish")
                or "I do not wish to answer")
    if any(k in q for k in ["race", "ethnicity", "hispanic", "latino"]) or is_race_opts:
        return pick_option("decline", "do not wish", "prefer not", "two or more") or "Decline to self-identify"
    if "how did you hear" in q or "referral source" in q:
        return pick_option("indeed", "job board", "online") or "Indeed"
    # Indeed's own "share answers" prompt
    if "share these answers" in q or "save my answers" in q or "answers you answer will be shared" in q:
        return pick_option("save") or None

    # Work authorization / citizenship / sponsorship — HONEST, from profile.
    # Bob = Green Card Holder: authorized to work, NO sponsorship, NOT a US citizen.
    is_gc = "green card" in (profile.get("visa_status", "").lower())
    authorized = bool(profile.get("work_authorization", True))
    needs_sponsor = bool(profile.get("requires_sponsorship", False))

    if any(k in q for k in ["authorized to work", "work authorization", "legally authorized",
                            "eligible to work", "lawfully authorized"]):
        return pick_option("yes") or ("Yes" if authorized else "No")
    if "require sponsorship" in q or "need sponsorship" in q or "visa sponsorship" in q \
            or "sponsorship now or in the future" in q:
        return pick_option("no") or ("No" if not needs_sponsor else "Yes")
    if "green card" in q or "permanent resident" in q or "lawful permanent resident" in q:
        return pick_option("yes") or ("Yes" if is_gc else "No")
    if "us citizen" in q or "u.s. citizen" in q or "citizenship" in q or "citizen of the united states" in q:
        # HONEST: Bob is a Green Card holder, NOT a US citizen.
        # If it only asks eligibility/authorization to work, answer Yes.
        if "authorized" in q or "eligible to work" in q:
            return pick_option("yes") or "Yes"
        # Strict "are you a citizen" -> No. For a radio, pick the "No" option.
        # For a text field, be explicit that Bob is a Green Card holder authorized to work.
        if field_type in ("radio", "select") and opts:
            return pick_option("no") or "No"
        return "No - Green Card holder (authorized to work in the U.S.)"
    if "felony" in q or "convicted" in q or "criminal" in q:
        return pick_option("no") or "No"
    if "background check" in q or "drug test" in q or "drug screen" in q:
        return pick_option("yes") or "Yes"
    # Security clearance / Public Trust — Bob has none. Answer honestly "No".
    if "public trust" in q or "security clearance" in q or "clearance" in q or "polygraph" in q:
        # A DATE question about a clearance Bob doesn't have -> leave blank (optional).
        if any(k in q for k in ["when was", "when did", "date of", "last adjudicated",
                                "adjudicated", "investigation date", "expiration"]):
            return None
        if any(k in q for k in ["active", "current", "currently hold", "do you have", "possess",
                                "hold current", "granted"]):
            return pick_option("no") or "No"
        if "eligible" in q or "able to obtain" in q or "willing to obtain" in q:
            return pick_option("yes", "eligible") or "Yes"
        return pick_option("no") or "No"

    # Experience (years)
    if "years" in q and any(k in q for k in ["experience", "exp"]):
        yrs = str(profile.get("years_experience", 10))
        return pick_option(yrs) or yrs

    # Education (never a Yes/No answer — guard against misfiring on Yes/No radios)
    yn_only = set(o.lower() for o in opts) <= {"yes", "no"} and len(opts) > 0
    if any(k in q for k in ["education", "degree", "highest level"]) and not yn_only:
        return pick_option("bachelor") or "Bachelor's"

    # Forms of identification (I-9 style). Bob is a Green Card holder -> I-551.
    if "identification" in q or "form of id" in q or "forms of id" in q or "government id" in q:
        return (pick_option("i-551", "permanent resident", "alien registration",
                            "green card", "driver", "license", "passport", "state id")
                or "Permanent resident card (Form I-551)")

    # Location / state / relocation / remote
    if "what state" in q or "which state" in q or ("state" in q and field_type == "select"):
        full = "Colorado"
        return pick_option(full, profile.get("state", "CO")) or full
    if "reside" in q and field_type == "select":
        return pick_option("Colorado") or "Colorado"
    if "relocate" in q:
        return pick_option("no") or "No"
    if "remote" in q and field_type in ("radio", "select"):
        return pick_option("yes", "remote") or "Yes"

    # Consent / data-processing / application-confirmation agreement (LEARNED 2026-09-02
    # from Gravity 9 job): "I consent to the processing of my personal data ...",
    # "By sending us your application, you confirm that you have read ...".
    # These are Yes / Yes-No radios — answer Yes (agree). MUST come before the salary
    # rule, whose old bare-substring "rate" match false-fired on "sepaRATEly" /
    # "incorpoRATEd" and returned the salary number "75" for these consent radios.
    yn_opts = set(o.lower() for o in opts) <= {"yes", "no"} and len(opts) > 0
    if any(k in q for k in ["i consent", "consent to the processing", "processing of my personal",
                            "by sending us your application", "you confirm that you have read",
                            "read and understood", "i agree to the", "agree to the terms",
                            "terms and conditions", "privacy policy", "privacy notice",
                            "data protection", "gdpr"]):
        return pick_option("yes", "i agree", "agree", "i consent") or "Yes"

    # Salary / rate / compensation — from profile rate_target (hourly C2C).
    rate = str(profile.get("rate_target", 75))
    opts_l = " | ".join(opts).lower()
    # Annually vs Hourly choice -> Hourly (Bob works C2C hourly).
    # Detect by question text OR by the options themselves being Annually/Hourly.
    if field_type in ("radio", "select") and (
            _has_word(q, "annually", "hourly", "per year", "per hour")
            or ("annually" in opts_l and "hourly" in opts_l)):
        return pick_option("hourly", "hour", "per hour") or "Hourly"
    # "Enter the amount ($)" or any salary/rate/pay/compensation question -> the number.
    # Use WHOLE-WORD matching (not bare substring) so "rate"/"pay"/"amount" don't
    # false-match "separately"/"company"/"paycheck-unrelated" words. Never return a
    # bare number for a Yes/No radio (a number can't be a Yes/No option).
    if not yn_opts and _has_word(q, "salary", "compensation", "rate", "pay expectation",
                                 "hourly", "expected pay", "desired", "amount", "how much",
                                 "enter the amount"):
        return rate

    # Start date / availability / notice
    if any(k in q for k in ["earliest date", "start date", "available to start",
                            "availability", "notice period", "when can you start"]):
        return "Immediately"

    # Do you meet the requirements / qualified
    if "meet the requirements" in q or "meet the qualifications" in q or "qualified" in q:
        return pick_option("yes") or "Yes"

    # Willing to / able to
    if q.startswith("are you willing") or q.startswith("are you able") or "willing to" in q:
        return pick_option("yes") or "Yes"

    # "Why do you want to work" essay
    if "why do you want to work" in q or "why are you interested" in q or "why this" in q:
        title = profile.get("title", "Java Back-End Developer")
        return (f"I bring {profile.get('years_experience', 10)}+ years as a {title} "
                "with strong Spring Boot, microservices, Kafka, and AWS experience. "
                "I'm excited to contribute reliable, well-tested backend systems to your team.")

    # Phone / email / name — from profile
    if "phone" in q:
        return profile.get("phone")
    if "email" in q:
        return profile.get("email")
    if "linkedin" in q:
        return profile.get("linkedin")
    if "github" in q:
        return profile.get("github")

    # Generic Yes/No radio we don't recognize → default Yes only if binary yes/no
    if field_type == "radio" and opts:
        yn = pick_option("yes")
        if yn and len(opts) <= 3:
            return yn

    return None


def _ask_user(question: str, field_type: str, options) -> str | None:
    """Prompt the user on the console. Returns their answer, or None if unavailable."""
    print("\n" + "=" * 60)
    print("🤔 UNKNOWN QUESTION — please teach me the answer:")
    print(f"   Q: {question}")
    print(f"   type: {field_type}")
    if options:
        print(f"   options: {list(options)}")
    print("=" * 60)
    try:
        ans = input("   Your answer (blank = skip): ").strip()
    except EOFError:
        return None
    return ans or None


def answer_question(db, question: str, field_type: str = "text",
                    options=None, profile: dict | None = None,
                    company: str = "") -> str | None:
    """Return the best answer for a question, learning + remembering as it goes.

    Order: memory -> profile rules -> GEMINI AI (dynamic, from CV) -> ask user.
    Any answer is saved to memory for instant reuse next time.
    """
    question = (question or "").strip()
    if not question:
        return None
    profile = profile or {}

    # 1. MEMORY
    remembered = get_approved_answer(db, question)
    if remembered:
        return remembered

    # 2. PROFILE RULES
    ans = _profile_answer(question, field_type, options, profile)
    if ans:
        save_approved_answer(db, question, str(ans), source="profile")
        return str(ans)

    # 3. GEMINI AI FALLBACK (dynamic) — ask AI what Bob should answer, from his CV.
    #    This handles NEW question wordings we haven't hard-coded. Saved to memory.
    try:
        try:
            from src.ai_fallback import ask_ai_about_field
        except Exception:
            from ai_fallback import ask_ai_about_field
        ai = ask_ai_about_field(question, field_type, options)
        if ai:
            # If options exist, snap the AI answer to the closest real option.
            if options:
                opts = [str(o) for o in options]
                match = next((o for o in opts if o.lower() == ai.lower()), None) \
                    or next((o for o in opts if ai.lower() in o.lower() or o.lower() in ai.lower()), None)
                ai = match or ai
            save_approved_answer(db, question, str(ai), source="gemini")
            print(f"      🤖 AI answered: {question[:40]!r} -> {str(ai)[:30]!r}")
            return str(ai)
    except Exception as _e:
        print(f"      ⚠️ AI fallback error: {str(_e)[:50]}")

    # 4. ASK USER (interactive local only)
    if _can_ask_user():
        ans = _ask_user(question, field_type, options)
        if ans:
            save_approved_answer(db, question, ans, source="user")
            return ans

    # Unknown and cannot ask (CI) — return None so caller can decide.
    return None
