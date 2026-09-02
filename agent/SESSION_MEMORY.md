# Job-Finder Indeed Auto-Apply — Session Memory (2026-09-01)

> Read this FIRST next session. Do NOT rebuild what's already here.

## What was built (all in `agent/`)
- **`submit_one.py`** — the working step-by-step Indeed SmartApply submitter (the main file).
- **`src/question_answerer.py`** — self-learning answer engine (memory → profile → ask-user).
- **`src/questions_filler.py`** — fills radios, textareas, text/date inputs, native + custom dropdowns, EEO.
- **`check_email_confirmations.py`** — reads Gmail for Indeed "Application submitted" emails → `data/email_confirmed_titles.json`.

## PROVEN WORKING (verified by real confirmation emails to bobrikh75@gmail.com)
5+ real submits: JSR Tech (26-00197), Akiak, MO Senior SWE, Constellation/ACS WEB, Senior iOS Dev, Java Dev 26-00525.
- Full flow: resume-selection → questions (50%) → EEO/demographic (88%) → **"Review your application"** → Submit (100%) → post-apply confirmation.
- Auto-CAPTCHA: `_try_auto_captcha_solve` (from `src/applier.py`) chain — reCAPTCHA Enterprise + audio (playwright-recaptcha) + Gemini — clears CAPTCHAs with NO human. Needs `GEMINI_API_KEY`.

## KEY FIXES LEARNED (do not re-discover)
1. **Advance button on the demographic/EEO page is "Review your application", NOT "Continue".** This was the #1 blocker. `click_continue` matches both.
2. **Race dropdown** = `<div role=combobox aria-haspopup=dialog data-testid="single-select-question-select-list-select-list">`. Options include "Decline to self-identify". Click `[role=option]` scoped to the open list (not page-wide get_by_text, which grabs same-text radios).
3. **Citizenship = No / Green Card holder** (honest). Work-auth=Yes, sponsorship=No, clearance/Public Trust=No, ID="Permanent resident card (Form I-551)", salary=rate 75/Hourly, EEO=decline, attestation="Yes I agree", AI opt-out="No". Green-card questions=Yes.
4. **Submit is below the resume preview** → scroll to bottom + JS `.click()` (strategy 4). Verify submit ONLY by real confirmation (post-apply URL or "application submitted" text) — NOT "page changed" (false positive).
5. **AI opt-out disclaimer** contains "education" → guard the Education rule to skip Yes/No radios.
6. **Skip already-applied**: by jk (`data/applied_jks.json`), by greyed "Applied" button (records jk), by title (`email_confirmed_titles.json` + `applied_titles.json`, match REAL h1 title only, len>=15 — NOT nav chrome). Skip repeatedly-failed (`data/failed_jks.json`).
7. **Reload-on-robot**: reloading clears the "I'm not a robot" checkbox (Bobur's tip).

## CLOUDFLARE (the open item) — SOLUTION IN PROGRESS
- Root cause: `src/stealth_toolkit.py` exists (7 tools: SeleniumBase UC, FlareSolverr, camoufox, nodriver, curl_cffi...) but NONE were installed → plain Playwright gets flagged by Cloudflare "Additional Verification Required".
- **FIX APPLIED: installed `patchright`** (stealth-patched Playwright, drop-in) + added to `agent/requirements.txt`. `submit_one.py` now imports `from patchright.sync_api import sync_playwright` (fallback to playwright). 2026 research: Patchright = cleanest Cloudflare-passing upgrade; SeleniumBase UC = surest; camoufox = strongest fingerprinting.
- NEXT: test that patchright passes Cloudflare on Indeed. If not enough, install `seleniumbase` (uc mode) or run FlareSolverr, or use `playwright-captcha` (techinz) for Turnstile.
- Turnstile checkbox CANNOT be reliably auto-clicked (by design) — patchright/stealth passes it NATURALLY, or reload clears it, or human clicks in HEADFUL=1 window.

## SELF-HEAL FLOW (built)
- `record_lesson(reason, step, pct)` → `data/flow_lessons.json`; `load_lessons()` applies fix next run (stuck→extra_reload_and_wait, submit_click_failed→longer_submit_poll).

## HOW TO RUN
```
cd ~/Downloads/CV/job-finder/agent
HEADFUL=1 FOCUS_ONE=1 TARGET_SUBMITS=1 ANSWERER_NO_ASK=1 python3 submit_one.py   # one job, watch
# CI/headless: omit HEADFUL. GEMINI_API_KEY in agent/.env (local) / GitHub secret (CI).
```
Env: `HEADFUL=1` (watch), `FOCUS_ONE=1` (stop after first real attempt), `TARGET_SUBMITS=N`, `ANSWERER_NO_ASK=1` (no console prompts).

## GIT
- Pushed to branch `feature/indeed-autoapply-captcha-selfheal` (NOT master). `.env` is gitignored (never commit GEMINI_API_KEY).
- `GEMINI_API_KEY` is in `agent/.env` locally AND a GitHub secret (CI). Value ends `...8HTY`.

## KEY LOCATIONS
- `data/applied_jks.json`, `data/failed_jks.json`, `data/applied_titles.json`, `data/email_confirmed_titles.json`, `data/flow_lessons.json`
- `config/profile.json` = Bob's CV data (visa=Green Card, rate 55/75/90, 10 yrs, CO).
- `data/schema.sql` seeds `approved_answers` (salary, work-auth, EEO defaults).
