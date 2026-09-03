# 🔒 FLOW LOCK — Indeed Auto-Apply (READ BEFORE EDITING ANYTHING)

**Status: APPROVED + FROZEN — verified by a REAL submitted application 2026-09-02**
(`jk=34729111d7580f6e` → `🎉 CONFIRMATION: url:post-apply` → `✅ SUBMITTED #1`, 34s)

This flow WORKS end-to-end. The rules below exist so no future session breaks it while
fixing something else.

---

## The 4 LOCKED fixes (never change without Bobur's explicit approval)

Each is marked in-code between `# >>> LOCKED FIX #n` and `# <<< LOCKED FIX #n`.

| # | What | File | Why it must not change |
|---|------|------|------------------------|
| 1 | Persistent real-Chrome launch (`_launch`) | `submit_one.py` | Beats reCAPTCHA "Try again later / automated queries". Fresh Chromium + fake UA + manual args → instant bot block. |
| 2 | `GEMINI_MODEL = gemini-flash-latest` | `src/gemini_captcha_solver.py` | Old pinned preview model 404'd → AI solver silently failed. `-latest` never 404s. |
| 3 | Single-option consent auto-click | `src/questions_filler.py` | "Acknowledge"-only questions used to stick the flow at 50%. |
| 4 | Trust injected TOKEN, never reload-after-solve (x2) | `submit_one.py` | Reload threw away the solved token and bounced the flow to step 0 (`submit_click_failed@pct38%`). |

---

## Rules for ANY future change

1. **Do NOT touch the LOCKED blocks** to fix an unrelated problem.
2. **New/other fixes = OPTIONAL + ADDITIVE.** Gate behind an env flag, default OFF:
   ```python
   if os.environ.get('EXPERIMENTAL_<NAME>') == '1':
       ...new behavior...
   ```
   The locked default path stays exactly as-is.
3. **Confirm first, promote later.** Only after the new fix produces a REAL confirmed
   submit may it become the default — and only then update this file + `SESSION_MEMORY.md`
   + move its LOCKED markers.
4. **Optimize only after confirmation**, and only in an optional path first. Never
   "clean up" or "optimize" a locked block.
5. **If the flow regresses:** re-apply these exact 4 fixes. Do not invent new ones.

---

## How to run (unchanged)
```bash
cd ~/Downloads/CV/job-finder/agent
HEADFUL=1 FOCUS_ONE=1 TARGET_SUBMITS=1 ANSWERER_NO_ASK=1 python3 submit_one.py
# retry previously-failed jobs:
HEADFUL=1 FOCUS_ONE=1 TARGET_SUBMITS=1 ANSWERER_NO_ASK=1 RETRY_FAILED=1 SEARCH_TERM="Java developer remote" python3 submit_one.py
```
macOS has no `timeout` → use `gtimeout` or a background+sleep-kill guard.

Full detail: `SESSION_MEMORY.md` → "APPROVED + FROZEN" section.
