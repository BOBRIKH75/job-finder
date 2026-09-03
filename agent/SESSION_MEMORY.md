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


---
## Session: 2026-09-02 PM — CAPTCHA "Try again later" SOLVED end-to-end ✅ (APPROVED + FROZEN)

> ⛔ FLOW IS APPROVED AND FROZEN. Next session: DO NOT rebuild, DO NOT guess, DO NOT skip,
> DO NOT change these 4 fixes. They are verified working by a REAL submitted application
> (`jk=34729111d7580f6e` → `🎉 CONFIRMATION: url:post-apply` → `✅ SUBMITTED #1`, took 34s).
> This is already covered. If it regresses, RE-APPLY these exact fixes — do not invent new ones.

### The problem (from Bobur's 2 screenshots)
Indeed SmartApply `review-module` page → reCAPTCHA showed **"Try again later — Your computer or
network may be sending automated queries."** This is NOT a solvable puzzle — it is Google's
risk engine giving the session a ~0 trust score and refusing to SHOW any challenge. You cannot
AI-solve a block that never presents a grid. Confirmed via web + CapSolver 2026 + browseract 2026.

### ROOT CAUSES (4 real bugs found + fixed — all verified)
1. **Launch config killed patchright stealth** (`submit_one.py` `_launch()`).
   - WAS: `pw.chromium.launch(headless=..., args=['--disable-blink-features=AutomationControlled'])`
     + `new_context()` (fresh, no profile) + a FAKE hardcoded `user_agent`.
   - WHY BAD: fresh Chromium + no cookies/history + a manual arg patchright ALREADY adds itself
     + fake UA = near-zero trust = "Try again later". (Per official patchright README "Best Practice".)
   - FIX (FROZEN): `pw.chromium.launch_persistent_context(user_data_dir='<agent>/.chrome-profile',
     channel='chrome', headless=not _headful, no_viewport=True)` — NO custom args, NO user_agent.
     Real Google Chrome (`patchright install chrome`, `/Applications/Google Chrome.app` present).
     Persistent profile keeps cookies across runs → Google trusts the session. `_launch()` now
     returns `(context, context, page)` — persistent context IS the browser (`.close()` works;
     no `.new_context()` calls exist, verified).
2. **Gemini AI solver model name was DEAD** (`src/gemini_captcha_solver.py`).
   - WAS: `GEMINI_MODEL = "gemini-2.5-flash-preview-05-20"` → **HTTP 404 on every call** (Google
     retired that preview). Solver caught the error and silently did nothing. THIS is why "we have
     a key but AI wasn't resolving" — the KEY IS VALID (ends ...8HTY), only the model name was dead.
   - FIX (FROZEN): `GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")`.
     Live-tested HTTP 200 (reply "OK"). `gemini-flash-latest` auto-tracks current flash → never 404s.
     Available models for this key incl: gemini-flash-latest, gemini-2.5-flash, gemini-3.5-flash.
3. **Single-option consent/acknowledge question got stuck at 50%** (`src/questions_filler.py`).
   - WAS: "Job Applicant Data Privacy Notice" whose ONLY option is "Acknowledge" → answer engine
     returned "Yes" (no match) → `could not click radio 'Yes' opts=['Acknowledge']` → stuck 2x → skip.
   - FIX (FROZEN, GENERIC — not tied to one job): in `_fill_radios`, if a radio group has exactly
     ONE option AND it contains a consent word (acknowledg/agree/consent/understand/accept/confirm),
     click that single option directly. Now flow reaches pct=100% review page.
4. **Destructive reload after CAPTCHA solve bounced the flow to step 0** (`submit_one.py`).
   - WAS: audio solver injected a valid token, but the recaptcha WIDGET IFRAME lingers in the DOM,
     so `has_recaptcha()` stayed True → success return was skipped → fell to step-3 `page.reload()`
     which THREW AWAY the token and reset the page → `submit_click_failed@pct38%` (the bounce).
   - FIX (FROZEN): trust the solver's success by checking for an INJECTED TOKEN
     (`g-recaptcha-response` value length > 20) instead of widget presence. If token present →
     return True, DO NOT reload. Applied in BOTH `solve_captcha_fully_dynamic` (solver-chain step)
     AND the submit-page block (`has_recaptcha and not token` → re-loop; else proceed to Submit).
5. **DB log failed on null company** (minor, non-blocking): submit succeeded but
   `NOT NULL constraint failed: applications.company`. FIX: `upsert_application(..., company=...)`
   with dynamic fallback `job_company/employer/job_title/'Indeed Employer'`. `upsert_application(**kw)`.

### THE FLOW (approved order — do not reorder)
launch persistent real Chrome → open job → Apply with Indeed → resume-selection → questions
(single-option consent auto-Acknowledge; radios/dropdowns/EEO as before) → structured-data →
**review-module (pct=100%)** → CAPTCHA chain [0) click not-a-robot + human jitter → 1) free
ClickSolver → 2) `_try_auto_captcha_solve`: NopeCHA→playwright-recaptcha AUDIO→Gemini(now working)
→hCaptcha→Enterprise ; trust TOKEN not widget → NO reload] → click Submit → confirm `url:post-apply`.

### Files changed this session (all verified, `python3 -c ast.parse` OK on each)
- `submit_one.py` — persistent Chrome launch (#1), token-trust no-reload x2 (#4), company kwarg (#5), jitter.
- `src/gemini_captcha_solver.py` — model → `gemini-flash-latest` (#2).
- `src/questions_filler.py` — single-option consent auto-click (#3).

### HOW TO RUN (unchanged)
```
cd ~/Downloads/CV/job-finder/agent
HEADFUL=1 FOCUS_ONE=1 TARGET_SUBMITS=1 ANSWERER_NO_ASK=1 python3 submit_one.py           # normal
HEADFUL=1 FOCUS_ONE=1 TARGET_SUBMITS=1 ANSWERER_NO_ASK=1 RETRY_FAILED=1 SEARCH_TERM="..." python3 submit_one.py  # retry failed
```
macOS has NO `timeout` cmd → use `gtimeout` or background+sleep-kill guard.

### OPEN / IP note
- ClickSolver (`playwright_captcha`) import errors ("Cli...") — harmless, audio solver covers it. Leave.
- The persistent-profile trust fix works from a HOME IP. On GitHub Actions (datacenter IP) the
  "Try again later" may still fire (2nd cause = IP reputation) → would need a residential proxy
  (costs money — Bobur decides). Not needed for local runs.


---
## 🔒 FLOW-LOCK RULE (2026-09-02) — HIGHEST PRIORITY, NEVER FORGET

> Bobur's explicit instruction: this working submit flow is LOCKED. Next session must NOT
> break it. Fixes for OTHER issues must be OPTIONAL/ADDITIVE and only promoted after confirmed.

- The 4 verified fixes (launch #1, gemini model #2, consent #3, token-trust #4) are marked
  in-code between `# >>> LOCKED FIX #n` and `# <<< LOCKED FIX #n`. DO NOT edit those blocks
  without Bobur's explicit approval.
- Policy file: `agent/FLOW_LOCK.md` (single source of truth). Script header in `submit_one.py`
  top also states the rule.
- NEW/other fix → gate behind an env flag `os.environ.get('EXPERIMENTAL_<NAME>')=='1'`, default
  OFF. Keep the locked default path untouched. Confirm with a REAL submit → THEN promote to
  default → THEN update FLOW_LOCK.md + this memory + move the LOCKED markers.
- Optimize ONLY after confirmation, and only in an optional path first. Never optimize a locked block.
- If it regresses → re-apply these exact 4 fixes, do not invent new ones.
- Rule of work: no guessing, no skipping, this is already covered — build new work AROUND the
  locked flow, never through it.


---
## Session: 2026-09-02 PM (cont.) — 3 MORE fixes, all CONFIRMED by real submits

Verified: 3 real submits this round — jk=9ec8f0a8dcc3aaea, 40a2c4f9be4522b2 (+ earlier 34729111d7580f6e).

### NEW FIX A — reCAPTCHA token TTL guard (DYNAMIC, additive — NOT locked-block edit)
- reCAPTCHA tokens expire ~120s after issue. If CAPTCHA solved early (e.g. STEP 0) then
  questions take >2min, the token is STALE at Submit → Indeed rejects.
- Added helpers in `submit_one.py`: `_current_recaptcha_token`, `_stamp_token_if_present`,
  `ensure_fresh_captcha_token(page)` (+ `_RECAPTCHA_TTL_SECONDS=110`, `_last_token_at`).
  `ensure_fresh_captcha_token(pg)` is called RIGHT BEFORE `click_submit(pg)`: if token missing
  or older than 110s → re-run `wait_for_human_captcha` (the locked solver chain) → re-stamp.
- Dynamic: re-solves whenever needed, based on token age. No-op when token is fresh / no captcha.

### NEW FIX B — DB upsert auto-defaults any NOT NULL column (`src/memory.py`)
- `applications` has NOT NULL: company, job_title, job_url. Submit succeeded but DB record
  failed twice (`company`, then `job_title`) → `NOT NULL constraint failed`.
- `upsert_application(**kw)` now reads `PRAGMA table_info(applications)` and auto-fills ANY
  NOT NULL non-pk column with no default that the caller omitted ('unknown' for TEXT, 0 else).
  Permanent — never breaks on a missing column again. Also now passes real job_title from flow.

### NEW FIX C — distance / "job is far from you" warning (DYNAMIC, additive)
- Screenshot: "This job looks like it might be a little far from you... About 910.67 miles
  away... make sure this job location still works for you." Bob is remote-preferred → always proceed.
- Added `dismiss_distance_warning(page)` in `submit_one.py`: detects by TEXT (far from you /
  miles away / still works for you / this job location / a little far), clicks the proceed
  button (continue-button / Continue / Apply anyway / Continue application / Yes). Called at the
  TOP of each step-loop iteration. No-op if the warning isn't present. Works for ANY distance.

### Still open / notes
- ClickSolver (playwright_captcha) import error — harmless, audio solver covers it.
- GitHub Actions datacenter IP may still trip "Try again later" (IP reputation) → residential
  proxy needed there (Bobur decides). Local home-IP runs work.


---
## Session: 2026-09-02 evening — CI unified to submit_one.py + dedup git-sync

### ROOT CAUSE of "CI re-applies to already-applied jobs" + "Try again later on CI"
- CI ran a SEPARATE old submitter `indeed_apply.py` (root), NOT the fixed `agent/submit_one.py`.
  `indeed_apply.py` still had the OLD launch (plain `chromium.launch()` + `--no-sandbox` +
  `--disable-blink-features` + fake UA, no persistent profile) → the screenshot's "unsupported
  flag --no-sandbox" + "Try again later". My 4 locked fixes were only in submit_one.py.
- Dedup files (`applied_jks.json`, `applied_titles.json`, `email_confirmed_titles.json`) were
  UNTRACKED + never restored/committed by CI → CI had no idea what local runs applied to →
  re-applied to the same jobs. Only `agent_memory.db` went through a flaky Actions cache.

### FIX (Option A + dedup sync)
1. `.github/workflows/indeed-apply.yml` now runs `agent/submit_one.py` (the FIXED flow) — one
   submitter, no duplication. Env: INDEED_COOKIES, GEMINI_API_KEY, NOPECHA_API_KEY, GH_PAT,
   ANSWERER_NO_ASK=1, TARGET_SUBMITS=10, HEADFUL=1. Runner is `self-hosted` (home IP — so the
   "Try again later" datacenter-IP concern does NOT apply; comment in yaml confirms cookies are
   IP-bound). GEMINI/NOPECHA secrets exist; INDEED_COOKIES updated 2026-09-02.
2. Dedup now shared via GIT (not cache): the 4 dedup JSONs are committed. CI `git pull --rebase
   --autostash` BEFORE the run (restore) and commits them AFTER (`applied_jks/applied_titles/
   email_confirmed_titles/failed_jks/...`). Local runs share the same tracked files. No PII in
   them (job hashes + public titles only) — safe for the PUBLIC repo.
3. `submit_one.py load_cookies()` upgraded: reads INDEED_COOKIES base64 secret (CI) → file →
   browser_cookie3. Verified: secret decode OK (40 cookies).
4. `_launch()` now clears STALE Chrome SingletonLock/Cookie/Socket before launch — a crashed/
   killed prior run left the persistent profile locked → `launch_persistent_context` failed
   ("profile in use"). Removes only lock symlinks, keeps cookies/history. Critical for CI reruns.
5. `click_submit` more patient: 7 attempts, settle grows `1.2 + attempt*0.8s`. Fixes intermittent
   `submit_click_failed@pct100%` on the reCAPTCHA ENTERPRISE path (Enterprise token solved via
   Google reload endpoint — NOT a page reload — but the Submit button re-enables slowly).

### NOTE on the two entry points
- `agent/submit_one.py` = THE submitter (local + CI now). `indeed_apply.py` (root) = legacy,
  no longer used by CI. Do not add fixes to indeed_apply.py — everything lives in submit_one.py.


---
## Session: 2026-09-02 late — 2 more real bugs found by local testing + rate-limit insight

### BUG D — pick_option matched 'no' inside 'now' → WRONG sponsorship answer (serious)
- `question_answerer.pick_option("no")` used naive substring `if want in o`. For sponsorship
  options ["Yes, I will require sponsorship NOW or in the future", "No, I will not require..."],
  "no" matched inside "**no**w" → picked the YES option → told employers Bob NEEDS sponsorship
  (he's a Green Card holder — he does NOT). Also stuck the flow at 50%.
- FIX: `pick_option` is now WORD-AWARE — (1) exact match, (2) option STARTS WITH keyword,
  (3) word-boundary regex for short tokens (yes/no), substring only for longer phrases.
  Unit-tested: sponsorship→"No, I will not...", authorization→"Yes, I am authorized...", resident→Yes.
- This was giving WRONG answers on real applications. High-value fix.

### KEY INSIGHT — "Try again later" is now mostly SELF-INFLICTED by over-testing
- Data: across today's runs, audio solver "Solved" 3x early, then "rate-limited" 7x. 32 jobs
  applied. The audio solver (playwright-recaptcha) hammered Google's audio endpoint → Google
  temporarily RATE-LIMITED the IP → "Try again later / automated queries" appears → Enterprise
  fallback injects a token but the page still shows the block → submit_click_failed.
- Root cause of the LATER failures = transient IP rate-limit from too much testing, NOT a code
  bug. The flow itself works (6+ real confirmed submits). CURE: stop hammering; the limit clears
  in minutes–hours. Space out runs; don't loop-test the CAPTCHA path.

### BUG E — no backoff on rate-limit (fixed)
- Added `is_recaptcha_rate_limited(page)` (detects "try again later" + "automated queries").
- `wait_for_human_captcha` now: if rate-limited → wait 20s + reload once → if still blocked,
  return False so the caller SKIPS the job (don't burn Enterprise reloads). Graceful cooldown.

### Testing discipline (IMPORTANT for next session)
- Each real submit + CAPTCHA solve pushes the IP toward rate-limit. Do NOT loop-test submits.
- Prefer verifying logic changes with the unit-test style (like pick_option test) over live runs.
- If "Try again later" appears: it's rate-limit — WAIT, don't fight it. Space CI schedule already
  spreads runs (4x/day) which is fine; the damage today was rapid manual test runs.

### Still open
- reCAPTCHA Enterprise path submit_click_failed only happens WHEN rate-limited (audio blocked →
  Enterprise → page still shows "try again later"). Should resolve once IP cools + audio works
  again. The click_submit patience bump (7 tries) + rate-limit backoff both help.


---
## Session: 2026-09-02 late — THE audio-rate-limit SOLUTION (image-challenge fallback)

### Web research (Xewdy444 Playwright-reCAPTCHA README — the exact lib in use)
- The library solves reCAPTCHA v2 TWO ways: (1) AUDIO challenge (default — this is what gets
  IP-rate-limited), (2) IMAGE challenge via CapSolver (`image_challenge=True` + capsolver key).
- Our code only ever called the AUDIO path → when audio rate-limited → "Try again later".
- SOLUTION THAT ALREADY EXISTED: switch to the IMAGE challenge when audio is blocked. Same lib.
- Google official (support/6081888): "automated queries" = IP/network rate-limit; clears with a
  clean IP / time. So: stop hammering audio → use image solve instead.

### FIX (applied)
- `src/applier.py` audio-solver block: on "rate limit", now falls back to
  `recaptchav2.SyncSolver(page, capsolver_api_key=_cap).solve_recaptcha(wait=True, image_challenge=True)`.
  `_cap = CAPSOLVER_API_KEY or CAPSOLVER_KEY` (repo secret is named CAPSOLVER_KEY — the lib wants
  CAPSOLVER_API_KEY; we read both).
- If no CapSolver key → falls through to the FREE Gemini Flash GRID solver
  (`solve_captcha_with_gemini(page,"recaptcha")` inside solve_recaptcha_enterprise METHOD 3) —
  Gemini now works (model fixed) and is in local .env. So local has a FREE image fallback.
- CI workflow: added `CAPSOLVER_KEY` + `CAPSOLVER_API_KEY` env (from secrets.CAPSOLVER_KEY) to the
  submit_one step. CI now has BOTH image paths (CapSolver + Gemini).

### Full CAPTCHA chain now (order)
0 click not-a-robot → 1 ClickSolver → 2 audio; if audio RATE-LIMITED → 2b image via CapSolver →
3 OhMyCaptcha → 3.5 hCaptcha → 4 Enterprise token → METHOD3 Gemini FREE grid solver.
Plus: rate-limit backoff (20s cooldown+reload, skip if still blocked) at the top.

### LOCAL setup note (for Bobur)
- Local `.env` has GEMINI_API_KEY (free grid fallback works). It does NOT have CAPSOLVER_API_KEY.
  To enable the paid CapSolver image path locally too, add `CAPSOLVER_API_KEY=<value>` to
  agent/.env (the value is in the GitHub secret CAPSOLVER_KEY — secrets are write-only so copy it
  from wherever it was originally saved). Not required — Gemini covers the free path.
