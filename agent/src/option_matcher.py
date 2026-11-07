"""Map a screening-question answer onto an option that REALLY exists on the page.

Problem (Indeed run 42400290124): the answer engine returned '10' / 'Yes' but the radio
options were ['Yes','No'] / ['True','False'] / ranges, so no click matched and the job got
stuck at 43%. resolve_option() always returns one of `opts` (or None = no truthful option,
caller must skip the job instead of submitting garbage).

Truthful rules come from config/profile.json only.
"""
from __future__ import annotations

import re

try:
    from src.question_answerer import _is_unverified_skill_claim, _profile_answer
except Exception:  # run from agent/src
    from question_answerer import _is_unverified_skill_claim, _profile_answer

_YES = {"yes", "y", "true", "yeah", "yep"}
_NO = {"no", "n", "false", "nope"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9+$ ]", "", (s or "").lower()).strip()


def polarity(opt: str):
    """'yes' / 'no' / None for an option label (handles 'Yes, I do', 'No, I will not')."""
    t = (opt or "").strip().lower()
    first = re.split(r"[\s,.;:!-]+", t, maxsplit=1)[0] if t else ""
    if first in _YES:
        return "yes"
    if first in _NO:
        return "no"
    return None


def _bool_opts(opts):
    """Return {'yes': opt, 'no': opt} if the options are a yes/no style pair, else None."""
    d = {}
    for o in opts:
        p = polarity(o)
        if p and p not in d:
            d[p] = o
    return d if len(d) == 2 and len(opts) <= 3 else None


def _ans_polarity(ans):
    a = (ans or "").strip().lower()
    if not a:
        return None
    first = re.split(r"[\s,.;:!-]+", a, maxsplit=1)[0]
    if first in _YES:
        return "yes"
    if first in _NO or a in ("0", "none", "n/a"):
        return "no"
    return None


# ---- numbers / ranges -------------------------------------------------------
_NUM = r"\$?\s*(\d[\d,]*(?:\.\d+)?)\s*(k)?"


def _to_num(txt, k):
    v = float(txt.replace(",", ""))
    return v * 1000 if k else v


def parse_range(opt: str):
    """Parse '0-1','1 to 3','5+','10+ years','Less than 1','$80k-$100k' -> (lo, hi) or None."""
    t = (opt or "").lower().replace("–", "-").replace("—", "-")
    nums = [(_to_num(n, k)) for n, k in re.findall(_NUM, t)]
    if not nums:
        if re.search(r"\b(none|no experience)\b", t):
            return (0.0, 0.0)
        return None
    if re.search(r"(less than|under|below|up to|fewer than|<)", t):
        return (0.0, nums[0])
    if re.search(r"(\+|or more|more than|over|above|at least|>)", t) and len(nums) == 1:
        return (nums[0], float("inf"))
    if len(nums) >= 2:
        return (min(nums[0], nums[1]), max(nums[0], nums[1]))
    return (nums[0], nums[0])


def pick_by_number(opts, value):
    """Option whose range contains value (ties -> narrowest)."""
    best, best_w = None, None
    for o in opts:
        r = parse_range(o)
        if not r:
            continue
        lo, hi = r
        if lo <= value <= hi:
            w = (hi - lo, -lo)
            if best is None or w < best_w:
                best, best_w = o, w
    return best


def _years_wanted(q: str):
    m = re.search(r"(\d+)\s*\+?\s*(?:or more\s*)?(?:years|yrs)", q)
    return int(m.group(1)) if m else None


def _nearest_not_above(opts, value):
    """Fallback for ranges when value sits in a gap: highest option low-bound <= value."""
    cands = [(parse_range(o), o) for o in opts if parse_range(o)]
    cands = [(r, o) for r, o in cands if r[0] <= value]
    return max(cands, key=lambda x: x[0][0])[1] if cands else None


_ALIASES = {"containeriz": ("docker", "kubernetes"), "container orchestration": ("kubernetes",),
            "orchestrat": ("kubernetes",), "message queue": ("kafka", "rabbitmq"),
            "messaging": ("kafka", "rabbitmq"), "event streaming": ("kafka",),
            "nosql": ("mongodb", "cassandra"), "relational": ("postgresql", "mysql", "oracle"),
            "infrastructure as code": ("terraform",), "continuous integration": ("jenkins", "ci/cd"),
            "continuous delivery": ("jenkins", "ci/cd"), "observability": ("splunk", "datadog"),
            "monitoring": ("splunk", "datadog"), "api design": ("rest", "restful", "graphql"),
            "authentication": ("oauth2", "jwt"), "serverless": ("lambda",)}


def _alias_known(ql, profile):
    sk = {str(s).lower() for s in (profile.get("skills") or [])}
    return any(k in ql and any(v in sk for v in vals) for k, vals in _ALIASES.items())


# ---- main -------------------------------------------------------------------
def desired_polarity(q: str, ans, profile: dict):
    """Decide yes/no truthfully for a boolean question."""
    ql = q.lower()
    years = int(profile.get("years_experience", 10) or 10)
    if "sponsor" in ql:
        return "yes" if profile.get("requires_sponsorship", False) else "no"
    if any(k in ql for k in ("authorized to work", "legally authorized", "eligible to work",
                             "work authorization", "lawfully authorized", "legally able to work")):
        return "yes" if profile.get("work_authorization", True) else "no"
    if any(k in ql for k in ("relocate", "relocation")):
        return "no"
    if any(k in ql for k in ("on-site", "onsite", "on site", "in-office", "in office", "hybrid",
                             "commute", "come into the office", "work from our")):
        # Truthful only when the place named is where the candidate lives.
        place_ok = any(str(profile.get(k, "")).lower() in ql for k in ("city",) if profile.get(k)) \
            or re.search(r"\b(colorado|denver|parker)\b", ql)
        return "yes" if place_ok else "no"
    if "citizen" in ql and "authorized" not in ql and "eligible" not in ql:
        return "no"
    want = _years_wanted(ql)
    skill_claim = _is_unverified_skill_claim(ql, profile) and not _alias_known(ql, profile)
    if want is not None and ("experience" in ql or "exp" in ql):
        if skill_claim:
            return "no"
        return "yes" if years >= want else "no"
    if skill_claim:
        return "no"
    p = _ans_polarity(ans)
    if p:
        return p
    # numeric / unrelated answer ('10') for a yes/no question: re-derive without memory.
    for fb in (_profile_answer(q, "radio", ["Yes", "No"], profile),):
        p = _ans_polarity(fb)
        if p:
            return p
    return None


def _salary_value(opts, profile):
    rate = float(profile.get("rate_target", 75))
    rng = [parse_range(o) for o in opts]
    big = any(r and r[0] >= 1000 for r in rng)
    return rate * 2080 if big else rate


def resolve_option(question: str, opts, ans, profile: dict, field_type: str = "radio"):
    """Return the element of `opts` to select, or None when no truthful option exists."""
    opts = [str(o) for o in (opts or []) if str(o).strip()]
    if not opts:
        return None
    q = (question or "")
    ql = q.lower()
    profile = profile or {}
    a = (str(ans) if ans is not None else "").strip()

    # 2. yes/no style options (Yes/No, True/False, Y/N)
    b = _bool_opts(opts)
    if b:
        pol = desired_polarity(q, a, profile)
        return b.get(pol) if pol else None

    # 3. long yes/no sentences ("Yes, I will require..." / "No, I will not ...")
    pols = [(polarity(o), o) for o in opts]
    if all(p for p, _ in pols):
        pol = desired_polarity(q, a, profile)
        return next((o for p, o in pols if p == pol), None) if pol else None

    # exact match of the answer to an option label (non yes/no lists)
    for o in opts:
        if a and o.lower().strip() == a.lower():
            return o

    # 4. salary / rate options (annualised from profile)
    if any(k in ql for k in ("salary", "compensation", "pay", "rate", "hourly", "annual")) and \
            any(parse_range(o) for o in opts):
        v = _salary_value(opts, profile)
        return pick_by_number(opts, v) or _nearest_not_above(opts, v)

    # 5a. notice period / start date -> earliest option
    if any(k in ql for k in ("notice", "start date", "when can you start", "available to start", "availability")):
        for kw in ("immediate", "asap", "now", "1 week", "one week", "2 week", "two week", "less than"):
            for o in opts:
                if kw in o.lower():
                    return o

    # 5. numeric-range options (years of experience, counts)
    if sum(1 for o in opts if parse_range(o)) >= max(2, len(opts) - 1):
        if "year" in ql or "experience" in ql:
            val = 0.0 if _is_unverified_skill_claim(ql, profile) else float(profile.get("years_experience", 10))
        else:
            m = re.match(r"^\s*(\d+)", a)
            val = float(m.group(1)) if m else None
        if val is not None:
            return pick_by_number(opts, val) or _nearest_not_above(opts, val)
        return None

    # 7. text match (substring / first-word) as a last resort
    if a:
        for o in opts:
            if a.lower() in o.lower() or o.lower() in a.lower():
                return o
        a0 = a.lower().split()[0]
        for o in opts:
            if o.lower().split()[0] == a0:
                return o
    return None


def resolve_checkboxes(question: str, opts, profile: dict):
    """Pick checkbox options for a 'select all that apply' question: only skills in profile.
    Falls back to a 'none of the above' option; returns [] if nothing truthful."""
    opts = [str(o) for o in (opts or []) if str(o).strip()]
    skills = [str(s).lower() for s in (profile.get("skills") or []) if len(str(s)) >= 2]
    chosen = []
    for o in opts:
        ol = o.lower()
        if re.search(r"\b(none|n/a|not applicable)\b", ol):
            continue
        if any(re.search(r"(?<![a-z0-9])" + re.escape(s) + r"(?![a-z0-9])", ol) for s in skills):
            chosen.append(o)
    if chosen:
        return chosen
    none = next((o for o in opts if re.search(r"\b(none of|n/a|not applicable)\b", o.lower())), None)
    return [none] if none else []
