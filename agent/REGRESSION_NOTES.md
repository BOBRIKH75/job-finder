# Regression Notes — 2026-10-29 "real apply" overhaul

**Symptom reported:** the agent showed 1,205 Dice "applied" but only ~43 real email
confirmations, then **0 confirmations for 7 days**. "Is it actually applying to real jobs?"

**Verdict:** the apply engines were fine. The real applications had stopped because of a
**dead runner** + **three hidden bugs** that made it *look* like "no new jobs / already
applied / nothing to do." After the fixes, a live run produced **10 real Dice confirmation
emails in one day** (verified via Gmail `applyonline@dice.com`).

> ⚠️ Every fix below is locked by `tests/test_regression_2026_10_29.py`. If one of those
> tests fails, someone reverted a fix — re-read the matching section before "fixing" the test.

---

## Ground truth vs cache (read this first)
- `agent/data/dice_applied.json` / `dice_applied_ids.json` = **dedup cache** (jobs processed /
  already-applied / skipped). This is NOT proof of a submit.
- **Real proof = confirmation emails.** Use `agent/verify_real_applications.py`
  (or `/cv verify`) — it reads Gmail for actual `applyonline@dice.com` / platform
  "application sent" emails. That is the only honest scoreboard.

---

## BUG 1 — Runner dead since Sept 28 (not a code bug, an infra bug)
- The self-hosted GitHub Actions runner (`bobur-laptop`) was never installed as a service.
  A foreground `run.sh` died on sleep/logout and never came back. GitHub still showed it
  "online" (ghost session), so Dice/Indeed/LinkedIn jobs dispatched to a runner that wasn't
  there and queued forever.
- **Fix:** installed as a durable LaunchAgent service via `fix-runner.sh`
  (`~/gh-runner`, auto-start on login, restart on crash). Cleared the ghost session with a
  full `config.sh remove` + fresh `config.sh` re-register. Verified `Listening for Jobs`.
- **Also:** crons changed from fixed weekday business hours to **every 2 hours, 24/7**
  (`*/2`) on dice/indeed/greenhouse/agent, so jobs posted at night/weekends get caught.
- **Keep the laptop awake:** `sudo pmset -a sleep 0 disablesleep 1`.
- **Guarded by:** `test_appliers_run_every_2_hours_24x7`.

## BUG 2 — stdout buffering hid everything
- Appliers ran `python3 dice_apply.py` (buffered). Python held all output and flushed at
  exit, so a 10-minute run printed every line at the **same timestamp** — it looked instant
  and like it did nothing. This hid the real behavior and wasted debugging.
- **Fix:** run unbuffered — `PYTHONUNBUFFERED=1 python3 -u ...` (dice), `python3 -u ...`
  (greenhouse, linkedin).
- **Guarded by:** `test_appliers_run_unbuffered`.

## BUG 3 — Dice "already applied" false-positive (the big one)
- `_apply_one` decided "already applied" by scanning the **entire page body**
  (`document.body.innerText`) for phrases like `you applied`, `applied on`, `application
  sent`. A Dice job page almost ALWAYS contains the word "applied" somewhere ("People who
  applied", "X applicants", recommended-jobs rails). So it false-skipped **every fresh job**
  → `SUBMITTED 0` on 144 genuinely-new jobs.
- **Fix:** inspect ONLY the apply button/control text + aria-label (`[data-testid=apply-
  button]` etc.), never the whole body.
- **Guarded by:** `test_dice_already_applied_does_not_scan_whole_body`.

## BUG 4 — Dice wizard stalled at "incomplete"
- The multi-step easy-apply wizard filler was called as
  `fill_questions_page(page, None, {}, ...)` — **db=None, profile={}**. With no profile the
  answerer couldn't answer required screening questions (work auth, sponsorship, rate,
  years, EEO) → required fields empty → Next/Submit stayed disabled → wizard never reached
  confirmation → `incomplete` (seen 89x).
- **Fix:** thread the real `db` + loaded `profile` through `_apply_one` into
  `fill_questions_page`. `main()` keeps `_profile = load_profile()` (previously discarded as
  `_ = load_profile()`).
- **Guarded by:** `test_dice_apply_one_receives_db_and_profile`.

## BUG 5 — LinkedIn counted a click as an application (fake)
- LinkedIn set `submitted = True` the instant the Submit button click succeeded, with **no
  confirmation read** → overcounted.
- **Fix:** after clicking Submit, poll for a real `application sent` / `your application was
  sent` confirmation before counting.
- **Guarded by:** `test_linkedin_requires_confirmation_before_counting`.

## Supporting fixes
- **Dice dedup TTL (30d):** `dice_applied.json` / `_ids.json` were PERMANENT, so once the
  Java/Spring pool was in them every run skipped 100%. Added `APPLIED_TTL_DAYS=30` (legacy
  list re-opens; recent stays blocked; old expires) — mirrors Greenhouse's 30-day model.
  Guarded by `test_dice_dedup_ttl_reopens_backlog`.
- **Answerer safe default:** in CI (no human), unknown screening questions used to return
  `None` → empty field → stall. Now a safe, honest, non-empty default is returned so the
  wizard can advance, while the questions that matter keep their honest profile answers.
  Guarded by `test_answerer_never_returns_none_in_ci`.
- **Dice confirmation poll:** the post-submit check was a single instant read and missed
  Dice's async redirect/button-flip (logged `incomplete` while Dice emailed "sent"). Now it
  polls (`_confirm_with_wait`) and also accepts the apply button flipping to "Applied".

---

## How to verify any time
```bash
# real confirmed applications (ground truth, from Gmail)
cd ~/Downloads/CV/job-finder/agent && python3 verify_real_applications.py --days 1

# runner alive + listening?
cd ~/gh-runner && ./svc.sh status
tail -5 ~/Library/Logs/actions.runner.*/*.log      # want: "Listening for Jobs"

# run the regression lock
cd ~/Downloads/CV/job-finder/agent && python3 -m pytest tests/test_regression_2026_10_29.py -v

# trigger a live run + watch (unbuffered now, so logs are real-time)
cd ~/Downloads/CV/job-finder && gh workflow run dice-apply.yml
```

## Do NOT revert
- Fixed-hour weekday crons (kills 24/7).
- Buffered `python3` without `-u` (hides activity).
- Body-text `already applied` scan (false-skips every job).
- `fill_questions_page(page, None, {}, ...)` (empty profile → stall).
- LinkedIn click-without-confirmation counting (fake numbers).


---

# Part 2 — cross-platform audit + fixes (same day, after Dice)

Audited Indeed, LinkedIn, Greenhouse for the same 5 bug classes. Findings + fixes:

## Indeed — the LIVE applier is `agent/submit_one.py`, NOT `indeed_apply.py`
`indeed_apply.py` is **dead code** (no workflow runs it; it still has the old body-scan
false-positive, click=success, and a `_has_visible` NameError). The workflow runs
`submit_one.py`. Fixes applied to the LIVE one:
- **Unconfirmed submit counted as success (fake):** `submitted_no_conf` (Submit clicked but
  no confirmation verified) was lumped with real `submitted` → counted + permanently
  deduped. Now ONLY `submitted` counts/dedups; `submitted_no_conf` is left retryable.
- **Transient failures permanently retired:** `cloudflare_stuck` / `error` ('browser
  closed') were written to `failed_jks`/`dead_jks` and skipped forever. Now only genuinely
  unapplyable results (`stuck`/`no_apply_button`/`submit_click_failed`/`max_steps`) persist.
- **Loose confirmation URL:** `'applied' in u` matched any URL containing "applied" →
  require a real post-apply path segment (`post-apply`/`appliedconfirmation`/
  `/confirmation`/`application-submitted`).
- **Buffering:** workflow now runs `PYTHONUNBUFFERED=1 python3 -u submit_one.py`.
- Guarded by `test_indeed_*`.

## LinkedIn
- **Confirmation false-positive:** removed bare `"applied"` / `"application submitted"` from
  the confirmation match (LinkedIn shows "Applied"/"X applied" on non-confirmation pages).
  Keeps only reliable "sent" / "submitted to" phrases.
- **Over-gating** (why it never ran): was weekday-only + 8am–5pm + 20h cooldown + once-daily
  cron. Widened to **weekends allowed + 7am–8pm MT**. The **20h cooldown + per-run cap
  stay** — those are the real anti-ban protections (LinkedIn bans bots; do NOT remove them).
- Guarded by `test_linkedin_confirmation_no_bare_applied`, `test_linkedin_runs_on_weekends`.
- NOTE: LinkedIn applies are the riskiest (ban risk). This is intentionally the most
  conservative platform. Do not crank up volume.

## Greenhouse
- Bug classes 1–4 were already CLEAN (its browser `submit_and_verify` literally encodes the
  Dice fix; API path guards the OTP page).
- **`job_claims` permanent leak (bug class 5):** claims were added but NOT released for
  queued-but-unattempted (over-quota) jobs and when the browser batch threw → those roles
  were claimed forever and never retried. Fixes:
  - Release claims on the over-quota, batch-exception, and no-browser-run paths.
  - Added `_purge_stale_claims()` in `memory.py` (runs on `init_db`) — claims older than
    `CLAIM_TTL_HOURS` (default 24h) are purged, so an un-released claim can't block a role
    permanently. Claims are a short-lived lock, not a dedup record.
- **Operational note:** OTP/reCAPTCHA-gated Greenhouse boards need `GMAIL_APP_PASSWORD` +
  `NOPECHA_API_KEY`/`CAPSOLVER_KEY`; without them those specific boards can't complete.
- Guarded by `test_greenhouse_releases_claims_on_unattempted`, `test_job_claims_have_ttl_purge`.

## Do NOT revert (part 2)
- Indeed `submitted_no_conf` counting as success (fake confirmation).
- Indeed `'applied' in u` loose URL confirmation.
- LinkedIn bare `"applied"` confirmation substring.
- Greenhouse: leaving claims un-released / removing the claim TTL purge.
- Do NOT remove LinkedIn's 20h cooldown or per-run cap (anti-ban).


---

# Part 3 — Greenhouse big-company boards + Indeed Cloudflare

## Greenhouse `remix_context` parse failure (FIXED — real fix)
Big companies (Coinbase, Toast, Dropbox) moved their `job-boards.greenhouse.io` page to a
themed career site (clinchtalent / AWS WAF) with **NO `window.__remixContext`** in the HTML,
so `_get_job_data` returned None → "Cannot fetch job page / parse remixContext" → those jobs
dead-ended. Verified: the HTML parser returns None for coinbase, but the **official public
JSON API still works**: `GET boards-api.greenhouse.io/v1/boards/{company}/jobs/{id}?questions=true`
returns all 21 questions cleanly.
- **Fix:** added `_get_job_data_boards_api()` in `greenhouse_api.py` — when the HTML parse
  fails, fetch questions from the official API and normalize to the same shape the submit
  path expects (jobPost.questions + submitPath + confirmationPath). Submit still POSTs to
  `boards.greenhouse.io/{company}/jobs/{id}`.
- Guarded by `test_greenhouse_boards_api_fallback_exists`.
- Verified live: coinbase job 8175363 — old parser None, new fallback returns 21 questions
  incl. work-auth/sponsorship/LinkedIn.

## Indeed Cloudflare (IMPROVED — best-effort, honest)
Cloudflare Turnstile is adversarial; no code guarantees 100%. Root cause of the stall:
clicking the **cross-origin** Turnstile iframe checkbox from automation is NOT a trusted
gesture and does NOT clear a *managed* challenge; the old loop clicked + waited only 5s.
- **Fix (highest-ROI, per 2026 research):** WAIT for the challenge to auto-clear / for the
  `cf-turnstile-response` token to be minted (a trusted **headful real-Chrome** profile on a
  **residential IP** — your home laptop — auto-passes Turnstile silently, usually in a few–20s).
  New `_cf_token_present()` polls the token field; `_wait_out_cloudflare()` waits up to
  `CLOUDFLARE_WAIT` (now 30s) and only nudges the checkbox once, midway, as a last resort.
- Workflow already runs `HEADFUL=1` on the self-hosted laptop (residential IP) = best case.
- Guarded by `test_indeed_cloudflare_waits_for_token_not_just_click`, `test_indeed_runs_headful`.
- **Honest limit:** if Indeed ever flips your IP to a hard managed-challenge, only a
  residential proxy or a paid Turnstile solver (CapSolver `AntiTurnstileTaskProxyLess` →
  inject token into `cf-turnstile-response`, no reload) is deterministic. Those are additive,
  env-gated options to add later if needed — NOT wired in yet (keep it simple first).

## Do NOT revert (part 3)
- Greenhouse boards-api fallback (big-company jobs dead-end without it).
- Indeed CLOUDFLARE_WAIT back to 5s / click-only (auto-pass needs the longer token wait).
- Indeed HEADFUL=1 (headless gets hard managed challenges).
