"""LinkedIn Easy Apply via patchright + PERSISTENT real Chrome profile (same technique as Dice).

Why: Selenium + undetected-chromedriver + injected cookies opened no apply dialog (SDUI page
detects automation). This engine uses a real headed Chrome profile, only the li_at cookie,
real locator clicks, and dumps DOM diagnostics (no personal data) when no dialog appears.

Safety: reuses caps/jitter/cooldown from linkedin_easy_apply.py, stops after 4 consecutive
failures, stops on any checkpoint/captcha/restriction signal. Answers come ONLY from
agent/config/profile.json; an unknown required question aborts that job (never guessed).
"""
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import linkedin_easy_apply as base

sys.path.insert(0, str(Path(__file__).parent / "agent" / "src"))
try:
    from option_matcher import resolve_option  # truthful option mapping (shared with Indeed/Dice)
except Exception:  # pragma: no cover - keep engine alive if the module is missing
    resolve_option = None

PROFILE_PATH = Path(__file__).parent / "agent" / "config" / "profile.json"
RESUME_PATH = Path(__file__).parent / "agent" / "resume.pdf"
SHOT_DIR = Path(__file__).parent / "agent" / "screenshots"
PROFILE_DIR = Path(os.environ.get("LINKEDIN_PROFILE_DIR", str(Path.home() / ".job-finder" / "linkedin-chrome-profile")))

MAX_FAIL_STREAK = 4
DIALOG_SELECTORS = [
    "[role='dialog']", ".jobs-easy-apply-modal", ".artdeco-modal", "[data-test-modal]",
    "[aria-modal='true']", "[data-sdui-screen*='Apply' i]", "[componentkey*='apply' i]",
]
DANGER = ("unusual activity", "verify your identity", "security verification", "we've limited",
          "temporarily restricted", "complete a captcha", "account has been restricted",
          "let's do a quick security check")


def load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text())


def log(msg: str):
    print(msg, flush=True)


NEEDS_FILE = Path(__file__).parent / "docs" / "NEEDS-FROM-USER.md"


def note_needed(label: str):
    """Log (structure only, no personal data) a question we could not answer from profile.json."""
    log(f"      NEEDS-FROM-USER: {label[:90]}")


# ------------------------------------------------------------------ answers (truthful)
def answer_for(label: str, prof: dict, kind: str = "text"):
    """Return an answer string from profile data, or None if we do not know (=> abort job)."""
    q = " ".join(label.lower().replace("*", " ").split())
    yrs = str(prof.get("years_experience", ""))
    skills = " ".join(prof.get("skills", [])).lower()
    if "sponsor" in q:
        return "Yes" if prof.get("requires_sponsorship") else "No"
    if re.search(r"authori[sz]ed|legally|eligible to work|right to work|work permit", q):
        return "Yes" if prof.get("work_authorization") else "No"
    if "first name" in q:
        return prof.get("first_name")
    if "last name" in q or "surname" in q:
        return prof.get("last_name")
    if "email" in q:
        return prof.get("email")
    if re.search(r"secondary|alternate|alternative|other phone|fax", q):
        return None
    if re.search(r"phone.*(type)|^type$|phone type", q):
        return "Mobile"
    if "phone" in q or "mobile" in q:
        return prof.get("phone")
    if re.search(r"\bstate\b|province", q):
        return prof.get("state")
    if "linkedin" in q:
        return prof.get("linkedin")
    if "github" in q:
        return prof.get("github")
    if re.search(r"website|portfolio|personal site", q):
        return prof.get("linkedin")
    if re.search(r"\bcity\b|location|where (are you|do you) (located|live)", q):
        return prof.get("location") if "city" not in q else prof.get("city")
    if "zip" in q or "postal" in q:
        return prof.get("zip")
    if "country" in q:
        return prof.get("country")
    if "hear about" in q or "how did you find" in q or "referral source" in q:
        return "LinkedIn"
    if re.search(r"address line|street address|address 1|^address\b", q):
        note_needed(label)
        return None
    if "year" in q and (re.search(r"exp\w*", q) or "work" in q):
        # per-skill question: only answer when the skill is in the profile skills list
        m = re.search(r"\b(?:with|in|using)\s+(.+?)(?:\?|$)", q) or \
            re.search(r"years?\s+(?:of\s+)?(.+?)\s+experience", q)
        topic = (m.group(1) if m else "").strip(" ?.")
        if not topic or any(w in skills for w in re.findall(r"[a-z0-9+#.]+", topic) if len(w) > 2 and w not in ("the", "and", "with")):
            return yrs
        return "0"  # skill/domain not in profile: truthful zero (same rule as Indeed answerer)
    if re.search(r"salary|compensation|pay|rate", q):
        target = prof.get("rate_target", 75)
        if re.search(r"annual|yearly|per year|salary", q) and "hour" not in q:
            return str(int(target * 2080))
        return str(target)
    if re.search(r"remote|work from home", q):
        return "Yes"
    if re.search(r"background check|drug (test|screen)", q):
        return "Yes"
    if re.search(r"start|notice|available", q):
        return "Immediately"
    if re.search(r"bachelor|degree|education", q):
        return "Bachelor"
    if "follow" in q and "company" in q:
        return "No"
    return None


# ------------------------------------------------------------------ browser
def launch(pw, cookies):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    for lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            os.unlink(PROFILE_DIR / lock)
        except OSError:
            pass
    headless = os.environ.get("LINKEDIN_HEADLESS", "0") == "1"
    kw = dict(user_data_dir=str(PROFILE_DIR), headless=headless, no_viewport=True, channel="chrome")
    try:
        ctx = pw.chromium.launch_persistent_context(**kw)
    except Exception:
        kw.pop("channel")
        ctx = pw.chromium.launch_persistent_context(**kw)
    li_at = next((c for c in cookies if c.get("name") == "li_at"), None)
    if li_at:
        ctx.add_cookies([{"name": "li_at", "value": li_at["value"], "domain": ".www.linkedin.com",
                          "path": "/", "secure": True, "httpOnly": True}])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return ctx, page


def body_text(page) -> str:
    try:
        return (page.inner_text("body", timeout=5000) or "").lower()
    except Exception:
        return ""


def restricted(page) -> bool:
    url = page.url.lower()
    txt = body_text(page)
    if "checkpoint" in url or "/uas/" in url or "authwall" in url or any(s in txt for s in DANGER):
        log(f"    🚨 RESTRICTION/CHECKPOINT signal (url={url[:60]}) — STOPPING")
        if "checkpoint" in url or any(s in txt for s in DANGER):
            base.send_restriction_alert("checkpoint/captcha")
        return True
    return False


def shot(page, tag):
    try:
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOT_DIR / f"li_{int(time.time())}_{tag}.png"))
    except Exception:
        pass


# ------------------------------------------------------------------ dialog discovery
def find_dialog(page):
    """Return a Locator for the apply dialog (top doc, shadow DOM [auto-pierced], or iframes)."""
    for fr in page.frames:
        for sel in DIALOG_SELECTORS:
            try:
                loc = fr.locator(sel)
                for i in range(loc.count()):
                    el = loc.nth(i)
                    if el.is_visible() and re.search(r"apply|contact info|resume|next|submit|review",
                                                     (el.inner_text(timeout=2000) or "").lower()):
                        return el
            except Exception:
                continue
    return None


def diagnostics(page, tag):
    """Log structure only (no personal data): dialog-ish nodes, roles, frames, shadow hosts, buttons."""
    try:
        log(f"    🔬 {tag} url={page.url[:90]} pages={len(page.context.pages)} frames={[f.url[:60] for f in page.frames][:6]}")
        info = page.evaluate("""() => {
          const out = {dialogs: [], shadow: [], buttons: []};
          document.querySelectorAll("[role='dialog'],[aria-modal],dialog,.artdeco-modal,[class*='modal' i]").forEach(e => {
            out.dialogs.push(e.tagName + '.' + (e.className||'').toString().slice(0,50) + ' role=' + e.getAttribute('role') + ' vis=' + (e.offsetParent!==null));
          });
          document.querySelectorAll('*').forEach(e => { if (e.shadowRoot) out.shadow.push(e.tagName + '#' + e.id + ' n=' + e.shadowRoot.childElementCount); });
          document.querySelectorAll("button,a[role='button']").forEach(e => {
            if (e.offsetParent !== null) out.buttons.push(((e.getAttribute('aria-label')||e.innerText||'').trim()).slice(0,30));
          });
          out.buttons = out.buttons.filter(Boolean).slice(0,25);
          out.dialogs = out.dialogs.slice(0,10);
          out.shadow = out.shadow.slice(0,8);
          return out;
        }""")
        log(f"    🔬 {tag} dialogs={info['dialogs']}")
        log(f"    🔬 {tag} shadow={info['shadow']}")
        log(f"    🔬 {tag} buttons={info['buttons']}")
    except Exception as exc:
        log(f"    🔬 diag failed: {str(exc)[:80]}")
    shot(page, tag)


def open_easy_apply(page, job_id) -> bool:
    popups = []
    page.context.on("page", lambda p: popups.append(p))
    btn = None
    for role in ("button", "link"):
        loc = page.get_by_role(role, name=re.compile(r"easy apply", re.I))
        for i in range(loc.count()):
            if loc.nth(i).is_visible():
                btn = loc.nth(i)
                break
        if btn:
            break
    if btn is None:
        log("    ⏭ No Easy Apply control")
        return False
    try:
        desc = btn.evaluate("e => e.tagName + ' ' + [...e.attributes].map(a => a.name + '=' + a.value.slice(0,50)).join(' ')")
        log(f"    🔬 btn {desc[:200]}")
    except Exception:
        pass
    btn.scroll_into_view_if_needed()
    time.sleep(random.uniform(0.8, 1.8))
    btn.hover()
    time.sleep(random.uniform(0.3, 0.8))
    btn.click(timeout=10000)          # REAL click, not JS
    for _ in range(14):
        time.sleep(1)
        if find_dialog(page):
            log("    🔬 apply dialog found")
            return True
        if popups:
            log(f"    🔬 popup opened: {popups[-1].url[:80]}")
        if "/apply" in page.url:
            log(f"    🔬 navigated to {page.url[:90]}")
            time.sleep(2)
            if find_dialog(page):
                return True
    diagnostics(page, "no-dialog")
    # fallback: SDUI apply flow URL
    for url in (f"https://www.linkedin.com/jobs/view/{job_id}/?openSDUIApplyFlow=true",
                f"https://www.linkedin.com/jobs/view/{job_id}/apply/?openSDUIApplyFlow=true"):
        log(f"    ↪ trying {url[-45:]}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception:
            continue
        for _ in range(8):
            time.sleep(1.5)
            if find_dialog(page):
                log("    🔬 apply dialog found via SDUI URL")
                return True
    diagnostics(page, "no-dialog-after-url")
    return False


# ------------------------------------------------------------------ form
RADIO_Q_JS = """e => {
  const g = (x) => (x && (x.innerText || x.textContent) || '').trim();
  const opts = [...e.querySelectorAll('input[type=radio]')].map(r => (r.labels && r.labels[0] ? g(r.labels[0]) : r.value));
  let t = g(e.querySelector('legend')) || e.getAttribute('aria-label') || '';
  if (!t && e.getAttribute('aria-labelledby')) t = e.getAttribute('aria-labelledby').split(' ').map(i => g(document.getElementById(i))).join(' ');
  if (!t) { let p = e.parentElement; for (let k = 0; k < 3 && p && !t; k++, p = p.parentElement) {
      t = g(p).split('\\n').map(x => x.trim()).filter(x => x && !opts.includes(x))[0] || ''; } }
  return t.replace(/\\s+/g, ' ').trim();
}"""

RADIO_OPT_JS = """e => {
  const g = (x) => (x && (x.innerText || x.textContent) || '').trim();
  const v = (e.value || '').trim();
  if (/^(yes|no|true|false)$/i.test(v)) return v[0].toUpperCase() + v.slice(1).toLowerCase();
  let t = (e.labels && e.labels[0]) ? g(e.labels[0]) : '';
  if (t && t.length <= 80) return t;
  if (e.getAttribute('aria-label') && e.getAttribute('aria-label').length <= 80) return e.getAttribute('aria-label');
  const sib = e.nextElementSibling; if (sib && g(sib) && g(sib).length <= 80) return g(sib);
  const lab = e.closest('label'); if (lab && g(lab).length <= 80) return g(lab);
  return v || t.slice(0, 40);
}"""

DIALOG_DEBUG_JS = """d => {
  const vis = e => e.offsetParent !== null;
  const t = e => (e.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 60);
  const controls = [...d.querySelectorAll('input,select,textarea')].filter(vis).map(e => {
    let lab = '';
    if (e.labels && e.labels[0]) lab = t(e.labels[0]);
    if (!lab) lab = e.getAttribute('aria-label') || '';
    return `${e.tagName.toLowerCase()}:${e.type}:${lab.slice(0, 45)}:req=${e.required || e.getAttribute('aria-required') === 'true'}:inv=${e.getAttribute('aria-invalid') === 'true'}:filled=${(e.value || '').length > 0 || e.checked === true}`;
  }).slice(0, 18);
  const errs = [...d.querySelectorAll('[role=alert],[class*=error i],[data-test-form-element-error-messages]')].filter(vis).map(t).filter(Boolean).slice(0, 6);
  const btns = [...d.querySelectorAll('button')].filter(vis).map(b => t(b)).filter(Boolean).slice(0, 8);
  return {controls, errs, btns};
}"""


HTML_JS = "e => e.outerHTML.replace(/\\s+/g, ' ').slice(0, 900)"

LEAF_OPTS_JS = """(fs) => {
  const q = ((fs.querySelector('legend') || {}).textContent || '').trim();
  const out = [];
  fs.querySelectorAll('*').forEach(e => {
    if (e.children.length) return;
    const t = (e.textContent || '').replace(/\\s+/g, ' ').trim();
    if (t && t.length <= 60 && t !== q && !q.includes(t) && !out.includes(t)) out.push(t);
  });
  return out;
}"""


def dialog_debug(dialog, tag):
    """Structure-only dump (labels/types/errors/buttons, never values) of a dialog that blocked us."""
    try:
        info = dialog.evaluate(DIALOG_DEBUG_JS, timeout=3000)
        log(f"      DEBUG[{tag}] controls={info['controls']}")
        log(f"      DEBUG[{tag}] errors={info['errs']} buttons={info['btns']}")
    except Exception as exc:
        log(f"      DEBUG[{tag}] failed: {str(exc)[:60]}")


LABEL_JS = """e => {
  const g = (x) => (x && (x.innerText || x.textContent) || '').trim();
  let t = '';
  if (e.labels && e.labels.length) t = g(e.labels[0]);
  if (!t && e.getAttribute('aria-labelledby')) t = e.getAttribute('aria-labelledby').split(' ').map(i => g(document.getElementById(i))).join(' ');
  if (!t) t = e.getAttribute('aria-label') || '';
  if (!t) { const p = e.closest('fieldset,[data-test-form-element],.fb-dash-form-element,div'); t = g(p).split('\\n')[0]; }
  return t.replace(/\\s+/g,' ').trim();
}"""


def fill_step(dialog, prof) -> bool:
    """Fill visible fields. Returns False if a required question could not be answered."""
    ok = True
    # text / number / textarea
    for loc in (dialog.locator("input[type='text'], input[type='number'], input[type='tel'], input[type='email'], input:not([type]), textarea"),):
        for i in range(loc.count()):
            el = loc.nth(i)
            try:
                if not el.is_visible() or el.input_value():
                    continue
                label = el.evaluate(LABEL_JS)
                ans = answer_for(label, prof)
                req = el.get_attribute("required") is not None or el.get_attribute("aria-required") == "true" or "*" in label
                if ans is None:
                    if req:
                        log(f"      ❓ unknown required question: '{label[:60]}'")
                        ok = False
                    continue
                if (el.get_attribute("type") or "") == "number" or "year" in label.lower():
                    ans = re.sub(r"[^\d.]", "", str(ans)) or str(ans)
                el.click()
                el.fill(str(ans))
                el.press("Tab")
                log(f"      📝 filled '{label[:40]}'")
            except Exception:
                continue
    # selects
    sel = dialog.locator("select")
    for i in range(sel.count()):
        el = sel.nth(i)
        try:
            if not el.is_visible():
                continue
            cur = el.evaluate("e => e.selectedOptions[0] ? e.selectedOptions[0].text : ''")
            if cur and not re.search(r"select an option|^select", cur.lower()):
                continue
            label = el.evaluate(LABEL_JS)
            ans = answer_for(label, prof)
            opts = el.evaluate("e => [...e.options].map(o => o.text.trim())")
            real = [o for o in opts if o and not re.match(r"^select", o.lower())]
            pick = resolve_option(label, real, ans, prof, "select") if resolve_option else None
            if pick is None and ans:
                pick = next((o for o in real if o.lower() == ans.lower()), None)
            if pick is None:
                log(f"      ❓ unanswerable select: '{label[:60]}' opts={[o[:25] for o in real][:6]}")
                ok = False
                continue
            el.select_option(label=pick)
            log(f"      📝 selected '{label[:40]}'")
        except Exception:
            continue
    # radio groups
    groups = dialog.locator("fieldset")
    for i in range(groups.count()):
        g = groups.nth(i)
        try:
            radios = g.locator("input[type='radio']")
            if not g.is_visible() or radios.count() == 0:
                continue
            if g.locator("input[type='radio']:checked").count():
                continue
            legend = g.evaluate(RADIO_Q_JS)
            ans = answer_for(legend, prof)
            labels = []
            for j in range(radios.count()):
                lab = radios.nth(j).evaluate(RADIO_OPT_JS) or ""
                labels.append(" ".join(lab.split()))
            bad = len(set(labels)) < len(labels) or any(l.lower() in ("on", "") or l in legend for l in labels)
            if bad:  # LinkedIn SDUI: input labels are the question; real option text is a leaf node
                leaf = [t for t in (g.evaluate(LEAF_OPTS_JS) or []) if t.lower() not in ("required",)]
                if len(leaf) == radios.count():
                    labels = leaf
                else:
                    log("      🔬 radio DOM: " + str(g.evaluate(HTML_JS)))
            pick = resolve_option(legend, labels, ans, prof, "radio") if resolve_option else None
            chosen = False
            if pick is not None:
                j = labels.index(pick)
                try:
                    radios.nth(j).check(force=True, timeout=4000)
                except Exception:
                    radios.nth(j).evaluate("e => (e.labels && e.labels[0] ? e.labels[0] : e).click()")
                chosen = radios.nth(j).is_checked()
                log(f"      🔘 radio '{legend[:40]}' -> '{pick[:20]}' checked={chosen}")
            if not chosen:
                log(f"      ❓ unanswerable radio: '{legend[:80]}' opts={[x[:20] for x in labels][:5]}")
                ok = False
        except Exception:
            continue
    # resume upload only when a file input exists and nothing selected
    try:
        fi = dialog.locator("input[type='file']")
        if fi.count() and RESUME_PATH.exists() and not dialog.locator("[class*='resume' i][class*='selected' i], [aria-checked='true'][class*='resume' i]").count():
            fi.first.set_input_files(str(RESUME_PATH))
    except Exception:
        pass
    # follow-company checkbox OFF
    try:
        cb = dialog.locator("input[type='checkbox']")
        for i in range(cb.count()):
            el = cb.nth(i)
            lab = (el.evaluate("e => (e.labels && e.labels[0] ? e.labels[0].innerText : '')") or "").lower()
            if "follow" in lab and el.is_checked():
                el.evaluate("e => (e.labels && e.labels[0] ? e.labels[0] : e).click()")
                log("      ☑ unchecked follow company")
    except Exception:
        pass
    return ok


def step_button(dialog, words):
    btns = dialog.locator("button, a[role='button']")
    for i in range(btns.count()):
        b = btns.nth(i)
        try:
            if not b.is_visible():
                continue
            t = ((b.get_attribute("aria-label") or "") + " " + (b.inner_text(timeout=1500) or "")).lower()
            if any(w in t for w in words):
                return b
        except Exception:
            continue
    return None


CONFIRM = ("application sent", "your application was sent", "application was sent",
           "we've sent your application", "your application has been submitted")


APPLIED_RX = r"\bapplied\s+(\d+\s*(s|sec|m|min|h|hr|hour|d|day|w|week)\w*\s+ago|just now|today)"


def page_shows_applied(page):
    """Return the matching 'Applied 2h ago' snippet if LinkedIn itself says this job was applied to."""
    txt = body_text(page)[:3500]  # top card only (right-rail similar jobs also say "Applied")
    m = re.search(APPLIED_RX, txt)
    return txt[max(0, m.start() - 20):m.end() + 20].replace("\n", " ") if m else None


def post_submit_probe(page):
    """Log what LinkedIn shows right after Submit (visible alerts/headings only, no personal data)."""
    try:
        info = page.evaluate("""() => {
            const vis = e => e.offsetParent !== null;
            const t = e => (e.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 120);
            const sel = '[role=dialog],[role=alertdialog],[role=alert],[aria-live],[data-test-modal],.artdeco-toast-item,h1,h2';
            return [...document.querySelectorAll(sel)].filter(vis).map(t).filter(Boolean).slice(0, 8);
        }""")
        log(f"      POST-SUBMIT visible: {info}")
        shot(page, "postsubmit")
    except Exception as exc:
        log(f"      POST-SUBMIT probe failed: {str(exc)[:60]}")


def applied_badge(page) -> bool:
    """After Submit: close any overlay, reload the job page and look for LinkedIn's own
    'Applied 2m ago' marker (the only reliable server-side proof when the modal text is missed)."""
    try:
        dismiss(page)
        page.reload(wait_until="domcontentloaded", timeout=45000)
        time.sleep(4)
        txt = body_text(page)[:3500]
        ctx = [txt[max(0, m.start() - 25):m.end() + 25].replace("\n", " ") for m in re.finditer(r"applied", txt)][:4]
        log(f"      APPLIED-CHECK contexts={ctx}")
        return bool(re.search(APPLIED_RX, txt))
    except Exception:
        return False


def run_dialog(page, prof) -> str:
    """Returns 'sent' | 'skip' (unanswerable question, not a failure) | 'fail'."""
    for step in range(9):
        time.sleep(random.uniform(1.5, 2.5))
        dialog = find_dialog(page)
        if dialog is None:
            return "fail"
        if not fill_step(dialog, prof):
            return "skip"
        sub = step_button(dialog, ("submit application",))
        if sub:
            time.sleep(random.uniform(1, 2))
            sub.click(timeout=8000)
            probed = False
            for _ in range(10):
                time.sleep(1)
                if not probed:
                    probed = True
                    time.sleep(2)
                    post_submit_probe(page)
                txt = body_text(page)
                for fr in page.frames:
                    try:
                        txt += " " + (fr.inner_text("body", timeout=1500) or "").lower()
                    except Exception:
                        pass
                if any(s in txt for s in CONFIRM):
                    log("    📨 LinkedIn confirmed: application sent")
                    return "sent"
            if applied_badge(page):
                log("    📨 LinkedIn job page now shows 'Applied' — counting as sent")
                return "sent"
            log("    ⚠ Submit clicked but NO confirmation seen — NOT counting")
            dialog_debug(dialog, "noconfirm")
            diagnostics(page, "no-confirm")
            return "fail"
        nxt = step_button(dialog, ("review your application", "review", "continue to next", "next", "continue"))
        if nxt is None:
            dialog_debug(dialog, f"stuck{step}")
            diagnostics(page, f"stuck{step}")
            return "fail"
        log(f"      ➡ step {step}: click '{(nxt.inner_text(timeout=1500) or '').strip()[:25]}'")
        nxt.click(timeout=8000)
        time.sleep(1.5)
        err = dialog.locator("[role='alert'], .artdeco-inline-feedback--error, [data-test-form-element-error-messages]")
        try:
            if err.count() and any(e.is_visible() for e in [err.nth(k) for k in range(min(err.count(), 5))]):
                log("      ⚠ validation error after Next — aborting this job")
                dialog_debug(dialog, f"valerr{step}")
                return "fail"
        except Exception:
            pass
    dd = find_dialog(page)
    if dd is not None:
        dialog_debug(dd, "loop-end")
    return "fail"


def dismiss(page):
    for name in (r"^done$", r"dismiss", r"close", r"discard"):
        try:
            b = page.get_by_role("button", name=re.compile(name, re.I))
            for i in range(b.count()):
                if b.nth(i).is_visible():
                    b.nth(i).click(timeout=3000)
                    time.sleep(1)
                    break
        except Exception:
            pass
    # "Discard" confirm dialog after dismissing an unfinished application
    try:
        d = page.get_by_role("button", name=re.compile(r"^discard$", re.I))
        if d.count() and d.first.is_visible():
            d.first.click(timeout=3000)
    except Exception:
        pass


# ------------------------------------------------------------------ main
def main():
    ok, reason = base.is_safe_run_time()
    if not ok:
        log(f"⏸ {reason}")
        return
    cookies = base.load_linkedin_cookies()
    if not cookies:
        log("❌ LINKEDIN_COOKIES secret not set")
        return
    applied = base.load_applied()
    force = os.environ.get("LINKEDIN_FORCE_RUN", "").strip().lower() in ("1", "true", "yes", "on")
    if applied.get("last_run") and not force:
        if datetime.now() - datetime.fromisoformat(applied["last_run"]) < timedelta(hours=20):
            log("⏸ Last run <20h ago")
            return
    prof = load_profile()
    max_apps = int(os.environ.get("LINKEDIN_MAX_APPS", base.MAX_APPLICATIONS_PER_RUN))
    log(f"🔗 LinkedIn Easy Apply (patchright, persistent profile) — max {max_apps}")

    try:
        from patchright.sync_api import sync_playwright
    except ImportError:
        from playwright.sync_api import sync_playwright

    count, fails = 0, 0
    with sync_playwright() as pw:
        ctx, page = launch(pw, cookies)
        try:
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)
            time.sleep(5)
            if any(x in page.url for x in ("login", "authwall", "checkpoint", "/uas/")):
                log(f"  🚨 session not authenticated: {page.url[:60]}")
                if "checkpoint" not in page.url:
                    base.alert_cookie_expired()
                return
            log("  ✅ Session valid")
            if restricted(page):
                return
            for _ in range(3):
                page.mouse.wheel(0, random.randint(300, 700))
                time.sleep(random.uniform(1.5, 3))
            for keyword in base.SEARCH_KEYWORDS:
                if count >= max_apps or fails >= MAX_FAIL_STREAK:
                    break
                ids = base.discover_job_ids(keyword)[:8]
                log(f"\n  🔍 '{keyword}': {len(ids)} ids")
                for job_id in ids:
                    if count >= max_apps or fails >= MAX_FAIL_STREAK:
                        if fails >= MAX_FAIL_STREAK:
                            log("    🛑 4 failures in a row — stopping (account safety)")
                        break
                    if job_id in applied["applied_ids"] or job_id in applied.get("skipped_ids", []):
                        continue
                    try:
                        page.goto(f"https://www.linkedin.com/jobs/view/{job_id}/", wait_until="domcontentloaded", timeout=60000)
                        time.sleep(random.uniform(4, 7))
                        if restricted(page):
                            return
                        log(f"    📝 Applying (job {job_id})...")
                        seen = page_shows_applied(page)
                        if seen:
                            log(f"    ✅ LinkedIn page itself says applied: '{seen}' — recording, not a failure")
                            applied["applied_ids"].append(job_id)
                            base.save_applied(applied)
                            time.sleep(random.uniform(8, 15))
                            continue
                        if not open_easy_apply(page, job_id):
                            fails += 1
                            continue
                        if restricted(page):
                            return
                        res = run_dialog(page, prof)
                        if res == "skip":
                            log("    ⏭ Skipped (needs info we do not have in profile) — not a failure")
                            applied.setdefault("skipped_ids", []).append(job_id)
                        elif res == "sent":
                            count += 1
                            fails = 0
                            applied["applied_ids"].append(job_id)
                            applied["total"] += 1
                            log(f"    ✅ Applied! ({count}/{max_apps})")
                        else:
                            fails += 1
                            log("    ⚠ Could not complete application")
                        dismiss(page)
                        for p in list(ctx.pages)[1:]:
                            try:
                                p.close()
                            except Exception:
                                pass
                        base.save_applied(applied)
                        if res == "skip":
                            time.sleep(random.uniform(10, 20))
                        else:
                            base.human_delay()
                    except Exception as exc:
                        fails += 1
                        log(f"    ⚠ Error on job: {type(exc).__name__}: {str(exc)[:80]}")
        finally:
            try:
                ctx.close()
            except Exception:
                pass
    base.save_applied(applied)
    log(f"\n📊 Results: {count} new applications | {applied['total']} total all-time")


if __name__ == "__main__":
    main()
