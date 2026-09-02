"""Fill the Indeed 'Answer these questions from the employer' page.

Real DOM (verified live 2026-09-01):
  - Radios:    <input type="radio" name="q_..."> with a sibling <label>Yes/No</label>;
               the question text is the enclosing fieldset's legend/heading.
  - Textareas: <textarea name="q_..."> — its own label IS the question text.
  - Selects:   custom button-dropdowns (state, forms of ID) — click to open, pick option.

Strategy: for each required, still-empty field, read the question text, ask the
self-learning answerer (memory -> profile -> user), then fill. Returns True if all
required fields were filled (so Continue can advance).
"""
from __future__ import annotations

import time

try:
    from src.question_answerer import answer_question
except Exception:
    from question_answerer import answer_question


def _clean(text: str) -> str:
    return (text or "").replace("\xa0", " ").replace("*", "").strip()


def is_questions_page(page) -> bool:
    try:
        body = page.locator('body').inner_text(timeout=3000).lower()
    except Exception:
        return False
    return ('answer these questions' in body
            or 'questions from the employer' in body)


def _fill_textareas(page, db, profile, company):
    """Fill each required, empty textarea using its label as the question."""
    filled = 0
    areas = page.locator('textarea')
    n = areas.count()
    for i in range(n):
        el = areas.nth(i)
        try:
            if not el.is_visible(timeout=1000):
                continue
            if (el.input_value() or '').strip():
                continue  # already has content
            # label: aria-label, or the question text sitting above it
            label = el.get_attribute('aria-label') or ''
            if not label:
                label = el.evaluate(
                    """(e) => {
                        // walk up to find the question label text
                        let p = e.closest('div');
                        for (let k=0; k<4 && p; k++) {
                            const t = p.querySelector('label, legend, h2, h3, span');
                            if (t && t.textContent.trim().length > 8) return t.textContent.trim();
                            p = p.parentElement;
                        }
                        return '';
                    }"""
                )
            q = _clean(label)
            if not q:
                continue
            ans = answer_question(db, q, field_type='textarea', profile=profile, company=company)
            if ans:
                el.fill(ans)
                filled += 1
                print(f"      ✍️  textarea: {q[:50]!r} -> {ans[:40]!r}")
            else:
                print(f"      ⚠️ no answer for textarea: {q[:50]!r}")
        except Exception as e:
            print(f"      textarea fill err: {str(e)[:50]}")
    return filled


def _fill_text_inputs(page, db, profile, company):
    """Fill <input type=text|date|url|number> fields by their label/question."""
    filled = 0
    inputs = page.locator('input[type="text"], input[type="date"], input[type="url"], '
                          'input[type="number"], input[type="tel"], input[type="email"]')
    n = inputs.count()
    for i in range(n):
        el = inputs.nth(i)
        try:
            if not el.is_visible(timeout=800):
                continue
            if (el.input_value() or '').strip():
                continue
            itype = (el.get_attribute('type') or 'text').lower()
            label = el.get_attribute('aria-label') or el.get_attribute('placeholder') or ''
            if not label:
                label = el.evaluate(
                    """(e)=>{let p=e.closest('div');for(let k=0;k<4&&p;k++){const t=p.querySelector('label,legend,span');if(t&&t.textContent.trim().length>4)return t.textContent.trim();p=p.parentElement;}return '';}"""
                )
            q = _clean(label)
            if not q:
                continue
            # Date inputs need a real date, not "Immediately".
            if itype == 'date' or 'mm/dd/yyyy' in (label or '').lower() or 'date' in q.lower():
                ans = _future_date()
            else:
                ans = answer_question(db, q, field_type='text', profile=profile, company=company)
            if ans:
                el.fill(ans)
                filled += 1
                print(f"      ⌨️  input[{itype}]: {q[:45]!r} -> {ans!r}")
        except Exception as e:
            print(f"      text-input err: {str(e)[:50]}")
    return filled


def _future_date() -> str:
    """A start date ~2 weeks out, MM/DD/YYYY."""
    import datetime
    d = datetime.date.today() + datetime.timedelta(days=14)
    return d.strftime("%m/%d/%Y")


def _fill_radios(page, db, profile, company):
    """For each radio group, read the question (fieldset legend) and pick the answer."""
    filled = 0
    groups = page.evaluate(
        """() => {
            const names = new Set();
            document.querySelectorAll('input[type=radio]').forEach(r => r.name && names.add(r.name));
            const out = [];
            for (const name of names) {
                const radios = [...document.querySelectorAll(`input[type=radio][name="${name}"]`)];
                // question = nearest fieldset legend / heading above the group
                let q = '';
                let p = radios[0].closest('fieldset');
                if (p) { const lg = p.querySelector('legend'); if (lg) q = lg.textContent.trim(); }
                if (!q) {
                    let d = radios[0].closest('div');
                    for (let k=0; k<5 && d; k++) {
                        const t = d.querySelector('legend, h2, h3, span');
                        if (t && t.textContent.trim().length > 10) { q = t.textContent.trim(); break; }
                        d = d.parentElement;
                    }
                }
                const anyChecked = radios.some(r => r.checked);
                const opts = radios.map(r => {
                    let lab = '';
                    if (r.id) { const l = document.querySelector(`label[for="${r.id}"]`); if (l) lab = l.textContent.trim(); }
                    return lab;
                });
                out.push({ name, question: q, options: opts, checked: anyChecked });
            }
            return out;
        }"""
    )
    for g in groups:
        if g['checked']:
            continue  # already answered
        q = _clean(g['question'])
        opts = [o for o in g['options'] if o]
        ans = answer_question(db, q, field_type='radio', options=opts, profile=profile, company=company)
        if not ans:
            print(f"      ⚠️ no answer for radio: {q[:50]!r} opts={opts}")
            continue
        # find the option text that best matches the answer (exact/substring first)
        target = None
        for opt in opts:
            if opt.lower() == ans.lower():
                target = opt
                break
        if target is None:
            for opt in opts:
                if ans.lower() in opt.lower() or opt.lower() in ans.lower():
                    target = opt
                    break
        if target is None and opts:
            # map short canonical answers (e.g. "No active clearance" -> "No")
            a0 = ans.lower().split()[0] if ans.split() else ''
            for opt in opts:
                if a0 and opt.lower().split()[0] == a0:
                    target = opt
                    break
        # EEO/demographic fallback: 'Decline to self-identify' may not literally exist.
        # Match any prefer-not/decline/don't-wish option; else use the last option.
        if target is None and opts:
            ql = q.lower()
            opts_l = " ".join(opts).lower()
            is_eeo = any(k in ql for k in ["gender", "race", "ethnic", "veteran", "disability", "sex"]) \
                or any(k in opts_l for k in ["prefer not", "decline", "self-identify", "self identify",
                                             "hispanic", "do not wish", "non-binary"])
            declineish = any(k in ans.lower() for k in ["decline", "prefer not", "do not wish",
                                                        "not to answer", "self-identify"])
            if is_eeo and declineish:
                target = next((o for o in opts if any(k in o.lower() for k in
                              ["prefer not", "decline", "do not wish", "not to answer",
                               "don't wish", "self-identify"])), None) or opts[-1]
        clicked = False
        if target:
            for attempt in (
                lambda: page.get_by_text(target, exact=True).first.click(timeout=2000),
                lambda: page.get_by_text(target[:40], exact=False).first.click(timeout=2000),
                lambda: page.get_by_role("radio", name=target).first.check(timeout=2000),
            ):
                try:
                    attempt()
                    clicked = True
                    break
                except Exception:
                    continue
        if clicked:
            filled += 1
            print(f"      🔘 radio: {q[:45]!r} -> {target!r}")
        else:
            print(f"      ⚠️ could not click radio {ans!r} for {q[:40]!r} opts={opts[:3]}")
    return filled


def _select_question_text(page, combobox):
    """Read the question label above a custom combobox."""
    try:
        return combobox.evaluate(
            """(e) => {
                let p = e.closest('div');
                for (let k=0; k<6 && p; k++) {
                    const t = p.querySelector('label, legend, h2, h3, span');
                    if (t && t.textContent.trim().length > 8 &&
                        !t.textContent.toLowerCase().includes('select an option')) {
                        return t.textContent.trim();
                    }
                    p = p.parentElement;
                }
                return '';
            }"""
        )
    except Exception:
        return ''


def _fill_custom_combobox(page, db, profile, company):
    """Fill Indeed custom dropdowns: <div role=combobox aria-haspopup=dialog>.
    Open -> read real options -> answerer picks one -> click/check it."""
    filled = 0
    # Race and other EEO dropdowns are role=combobox aria-haspopup=dialog with a
    # select-list testid. Match those (native selects handled separately).
    boxes = page.locator('[role="combobox"][aria-haspopup="dialog"], '
                         '[data-testid$="-select-list-select-list"]')
    count = boxes.count()
    for i in range(count):
        box = boxes.nth(i)
        try:
            if not box.is_visible(timeout=1000):
                continue
            cur = (box.inner_text(timeout=1000) or '').strip().lower()
            if cur and 'select an option' not in cur:
                continue  # already chosen
            q = _clean(_select_question_text(page, box))
            box.scroll_into_view_if_needed(timeout=2000)
            box.click(timeout=3000)
            time.sleep(1.2)
            # options may be role=option OR checkbox rows. Read both by text.
            opts = page.evaluate(
                """() => {
                    const set = new Set();
                    document.querySelectorAll('[role="option"]').forEach(e => {
                        if (e.offsetParent) set.add(e.textContent.trim());
                    });
                    // checkbox rows: a checkbox with a nearby text label
                    document.querySelectorAll('input[type=checkbox]').forEach(c => {
                        if (!c.offsetParent) return;
                        const row = c.closest('label') || c.parentElement;
                        const t = row ? row.textContent.trim() : '';
                        if (t) set.add(t);
                    });
                    return [...set].filter(t => t.length > 1).slice(0, 60);
                }"""
            )
            ans = answer_question(db, q, field_type='select', options=opts,
                                  profile=profile, company=company)
            # Skip phone country-code dropdowns — never force-fill these.
            opts_blob = " ".join(opts).lower()
            looks_phone = sum(1 for o in opts if '(+' in o or o.strip().startswith('+')) >= 3
            if looks_phone:
                print("      ↩︎ skipping phone country-code dropdown")
                try:
                    page.keyboard.press('Escape')
                except Exception:
                    pass
                continue
            # EEO/demographic (Gender/Race/etc.) -> always a decline-style answer.
            is_eeo = any(k in q.lower() for k in ["race", "ethnic", "gender"]) or \
                any(k in opts_blob for k in ["hispanic", "decline to self", "two or more races"])
            if is_eeo and (not ans or not any(ans.lower() in o.lower() or o.lower() in ans.lower() for o in opts)):
                # prefer an explicit decline/prefer-not option; else fall back to the LAST option.
                decline = next((o for o in opts if any(k in o.lower() for k in
                               ["decline", "do not wish", "prefer not", "not to answer", "don't wish"])), None)
                ans = decline or (opts[-1] if opts else ans)
            if not ans:
                print(f"      ⚠️ no answer for dropdown: {q[:45]!r} opts={opts[:3]}")
                try:
                    page.keyboard.press('Escape')
                except Exception:
                    pass
                continue
            # narrow via search box ONLY for long lists (states); skip for short EEO lists
            if len(opts) > 15:
                try:
                    search = page.locator('input[placeholder*="Search to select" i], '
                                          '[role="dialog"] input, input[type="search"]').first
                    if search.is_visible(timeout=1200):
                        search.fill(ans[:18])
                        time.sleep(1)
                except Exception:
                    pass
            # Click the matching [role=option] FIRST (scoped to the open list, so we
            # don't accidentally grab a same-text radio elsewhere on the page).
            picked = False
            for target in (ans, ans.split('(')[0].strip(), ans[:24]):
                if not target:
                    continue
                try:
                    opt = page.locator('[role="option"]', has_text=target).first
                    if opt.is_visible(timeout=1500):
                        opt.scroll_into_view_if_needed(timeout=1500)
                        opt.click(timeout=2500)
                        picked = True
                        break
                except Exception:
                    pass
            # Fallback: plain text click (for non-role=option lists)
            for target in ((ans, ans.split('(')[0].strip(), ans[:24]) if not picked else ()):
                if not target:
                    continue
                try:
                    el = page.get_by_text(target, exact=False).last
                    if el.is_visible(timeout=1500):
                        el.scroll_into_view_if_needed(timeout=1500)
                        el.click(timeout=2500)
                        picked = True
                        break
                except Exception:
                    continue
            if picked:
                filled += 1
                print(f"      ▼ dropdown: {q[:45]!r} -> {ans!r}")
                time.sleep(0.5)
                # close the menu (multi-selects stay open)
                try:
                    page.keyboard.press('Escape')
                    time.sleep(0.3)
                except Exception:
                    pass
            else:
                print(f"      ⚠️ could not pick {ans!r} for {q[:40]!r} (opts={opts[:4]})")
                try:
                    page.keyboard.press('Escape')
                except Exception:
                    pass
        except Exception as e:
            print(f"      dropdown err: {str(e)[:60]}")
    return filled


def _fill_selects(page, db, profile, company):
    """Fill native <select> and Indeed custom button-dropdowns."""
    filled = 0
    # native selects
    sels = page.locator('select')
    for i in range(sels.count()):
        el = sels.nth(i)
        try:
            if not el.is_visible(timeout=800):
                continue
            cur = el.input_value()
            if cur and cur.lower() not in ('', 'select an option'):
                continue
            label = el.get_attribute('aria-label') or el.evaluate(
                """(e)=>{let p=e.closest('div');for(let k=0;k<4&&p;k++){const t=p.querySelector('label,legend,span');if(t&&t.textContent.trim().length>8)return t.textContent.trim();p=p.parentElement;}return '';}"""
            )
            opts = el.evaluate("(e)=>[...e.options].map(o=>o.textContent.trim())")
            q = _clean(label)
            ans = answer_question(db, q, field_type='select', options=opts, profile=profile, company=company)
            if ans:
                try:
                    el.select_option(label=ans)
                except Exception:
                    for o in opts:
                        if ans.lower() in o.lower():
                            el.select_option(label=o)
                            break
                filled += 1
                print(f"      ▼ select: {q[:45]!r} -> {ans!r}")
        except Exception as e:
            print(f"      select err: {str(e)[:50]}")
    # custom comboboxes
    filled += _fill_custom_combobox(page, db, profile, company)
    return filled


def fill_questions_page(page, db, profile, company: str = "") -> bool:
    """Fill all required fields on the questions page. Returns True if it looks complete."""
    print("    📝 Questions page detected — filling required fields")
    total = 0
    total += _fill_radios(page, db, profile, company)
    total += _fill_textareas(page, db, profile, company)
    total += _fill_text_inputs(page, db, profile, company)
    total += _fill_selects(page, db, profile, company)
    print(f"    📝 filled {total} field(s)")
    time.sleep(1)
    return total > 0
