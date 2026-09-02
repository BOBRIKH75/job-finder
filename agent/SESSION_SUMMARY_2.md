# Job-Finder Indeed Auto-Apply — Session 2 Summary (2026-09-02)

> Read this FIRST next session (also in KB `job-finder-indeed-autoapply`). Builds on agent/SESSION_MEMORY.md.

## ✅ WHAT PASSES (tested + confirmed working)
- **14 real applications email-confirmed** (ground truth in Gmail): JSR Tech, Akiak, MO Senior SWE,
  IRS CAS ×3, Blockchain Developer (Java), Java Developer w/Blockchain, Senior iOS Developer,
  ServiceNow Senior Staff IAM, Oracle Cloud Finance (Kocha), Software Engineer III, Java Dev 26-00525.
- **Full flow navigates every page type:** resume-selection → questions (50%) → structured-data
  (63%, "Review details") → EEO/demographic (88%, "Review your application") → review-module (100%) → Submit.
- **Answers (honest, from CV):** citizenship=No/Green Card, work-auth=Yes, sponsorship=No, clearance=No,
  ID=I-551, salary=75/Hourly, EEO=decline, attestation=Yes, AI opt-out=No, signature box=Bob Rikh,
  ServiceNow/STOCK-Act/PwC radios answered, dynamic Gemini AI fallback for unknown questions.
- **Radio click FIXED:** group-scoped (name+label) JS click + verify — no more clicking wrong question's "Yes".
- **Dedup:** skip by jk (pre-open) + "Applied" button + email-confirmed/applied titles + failed jks.
- **Loop detection:** submit→bounce-to-38% → skip; force-advance capped 3; no-progress 2x → screenshot+skip.
- **Perf:** FAST=1 (1 screenshot/step), ~34s/job walk. Per-job timing (took Ns / time=Ns on fail).
- **Stealth:** Patchright (active) + Camoufox (installed). requirements.txt has patchright/camoufox/playwright-captcha.
- **CI/CD:** all on master, GEMINI_API_KEY secret set, "Indeed Easy Apply" workflow ran SUCCESS.

## ⚠️ THE CAPTCHA REALITY (industry fact, deeply researched — NOT a code gap)
- reCAPTCHA **Enterprise** (score-based, on strict jobs like Oracle/ServiceNow) CANNOT be passed by
  free code alone. Free ClickSolver only reliably does Cloudflare Turnstile + low-difficulty reCAPTCHA.
- **HEADFUL mode WORKS:** free solver tries first; strict → human clicks it once → submits + emails. (proven: Oracle)
- **Headless auto WORKS only for non-strict** jobs; strict Enterprise → needs paid token (CapSolver/2Captcha ~$1-3/1000).
- Best free lever = high-trust fingerprint (Patchright/Camoufox) so hard challenge rarely appears.

## 🐛 TO FIX NEXT SESSION (prioritized)
1. **Screen-blocking (Bobur's ask):** HEADFUL pops the window + steals focus. FIX: launch headed but
   keep window in background / off-screen; only bring to front when a CAPTCHA needs the human.
   (Option A). Headless doesn't block screen but can't solve strict CAPTCHA (Option B needs CapSolver key).
2. **time=0s cascade:** after a long CAPTCHA wait, the browser/context sometimes dies → all subsequent
   jobs error instantly at time=0s. FIX: detect dead page/context → relaunch browser + continue.
3. **Many jobs stuck at 50% (36-38s):** a batch of questions-page variants stall. Read the
   NOPROGRESS screenshots to find the unhandled field type; extend questions_filler.
4. **check_email_confirmations returned "Found 0" once** — IMAP search flaky. FIX: make the IMAP
   query robust (the 14 are real; the checker glitched).
5. **Headless Cloudflare:** jobs print "SUBMIT ONE" then nothing in headless = Cloudflare block or
   silent error. FIX: detect + reload/skip cleanly; consider Camoufox for headless.
6. (Optional) Wire CapSolver key path for fully-unattended CI on strict-CAPTCHA jobs.

## HOW TO RUN
```
cd ~/Downloads/CV/job-finder/agent
# Proven mode (submits; window pops up — solve occasional CAPTCHA):
HEADFUL=1 FAST=1 TARGET_SUBMITS=5 ANSWERER_NO_ASK=1 python3 submit_one.py
# Headless (no screen block; only non-strict jobs submit):
FAST=1 TARGET_SUBMITS=5 ANSWERER_NO_ASK=1 python3 submit_one.py
# Fresh search: SEARCH_TERM="..." ; one-job debug: FOCUS_ONE=1 TARGET_SUBMITS=1
# Verify: python3 check_email_confirmations.py
```
Env: HEADFUL, FAST, FOCUS_ONE, TARGET_SUBMITS, ANSWERER_NO_ASK, SEARCH_TERM, SEARCH_LOCATION, RESULTS_WANTED.

## KEY FILES
- `submit_one.py` (main), `src/question_answerer.py` (answers+AI), `src/questions_filler.py` (fill radios/dropdowns/text/EEO/signature)
- `src/applier.py::_try_auto_captcha_solve` (solver chain), `src/stealth_toolkit.py` (7 stealth tools, mostly not installed)
- data/: applied_jks.json, failed_jks.json, applied_titles.json, email_confirmed_titles.json, flow_lessons.json, needs_resolution.json
- config/profile.json (CV), data/schema.sql (seed answers). GEMINI_API_KEY in agent/.env (gitignored) + GitHub secret.

## GIT
- All pushed to `master` (personal repo BOBRIKH75/job-finder). Feature branch also exists.
- .env gitignored — never commit the key.
