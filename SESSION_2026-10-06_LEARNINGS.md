# Session 2026-10-06 — Deep Audit + Fixes (read before touching apply/outreach)

## RUNNER (laptop "bobur-laptop")
- Kept dying: runner lived INSIDE the repo so every `git pull` wiped `.runner`/
  `.credentials` → "Not configured". FIX: moved to ~/gh-runner (separate folder),
  installed as service + `setup-autopull.sh` (LaunchAgent: git pull every 15 min +
  runner watchdog + `pmset -a sleep 0 disablesleep 1`). Added missing `linkedin` label.
- A hung job (AI Job Agent 15.6h) can JAM the single runner → all self-hosted jobs
  cancel. If applies=0 and runner busy, cancel the zombie run.

## OUTREACH (the real call-driver) — all live on master
- Was Resend sandbox → 0/40 sent for ~2 months (silent fail). FIX: Gmail SMTP,
  verified 40/40 then 60/60 sent with CV. Daily weekdays, cap 60.
- Emails the 45 REAL named recruiters (recruiter_job_leads.json) FIRST (was never used).
  NAMED_ONLY drops ~580 dead role inboxes (careers@/jobs@/noreply@).
- Response-aware suppression: INTERVIEW/INTERESTED/INFO_REQUEST = never re-contact;
  CITIZEN_REQUIRED/REJECTION = re-contact after OUTREACH_REENGAGE_DAYS (45);
  MAX_CONTACTS=3 then drop. do_not_contact.txt = permanent skip.
- STILL 0 replies from ~120 contacted → DELIVERABILITY (Gmail bulk → spam).
  NEXT LEVER: $10 sending domain + SPF/DKIM. Bob must buy the domain.

## APPLY CHANNELS — verified reality (do NOT re-chase)
- GREENHOUSE = best automated channel: API, no Cloudflare, submits for real.
  companies.json = 366 verified boards (probed live API). Dedup TIME-WINDOWED
  (GH_DEDUP_DAYS=14) so reposts re-apply. Most are SV product cos (don't hire C2C) —
  CV gate correctly skips them.
- DICE: self-refreshes DICE_COOKIES secret each run. Works when logged in.
- INDEED: ❌ CLOUDFLARE WALL — confirmed via real-browser screenshot ("Additional
  Verification Required / Ray ID"). patchright already a real browser; Selenium/
  AppleScript are LESS stealthy = worse. ~48/50 jobs = external-apply even when CF
  passes. Fixed real bug (`if urls: break` → collect all 18 terms → 4→73 jobs) but
  still 0 submits. DO NOT build Cloudflare-evasion. Indeed = 14 confirms in 2 months.
- LINKEDIN: DOM selector broke + anti-bot. Low priority.

## THE TRUTH FOR CALLS
~292 auto-applies → 0 callbacks. Calls come from: (1) 33 named recruiters in
RECRUITERS_TO_CALL.md (reply personally, templates in OUTREACH_TEMPLATES.md),
(2) email deliverability (domain), (3) Greenhouse. NOT Indeed/LinkedIn automation.

## 5-DAY CHECK (run from any machine)
```
gh auth switch --user BOBRIKH75
gh run list --repo BOBRIKH75/job-finder --limit 15
# find the latest Daily Report run id, then:
gh run view <id> --log | grep -E "Applied:|Replies:|Callbacks:|Reply rate"
```
