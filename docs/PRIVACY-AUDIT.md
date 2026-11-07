# Privacy audit (2026-10, round 3)

Repo visibility at audit time: **PUBLIC**. Method: `git grep` over tracked files (382) for phone,
email, address, SSN-like, key/token patterns. Values are NOT listed here: paths and counts only.
Counts = matching lines. Git history still contains everything listed (no history rewrite was done).

## Secrets / tokens
- No AWS/GitHub/OpenAI/Google/Slack key values, no private keys, no long token values found in tracked files.
- Mentions of cookie names (`li_at`, `JSESSIONID`) exist in 9 files (workflows, extract_li_cookies.py,
  linkedin_pw_apply.py, scripts/linkedin_keep_alive.py, credential_checker.py, docs) - names only, no values.
- `.gitignore` already excludes `.env`, `*_cookies.json`, `*.pem`, `*.key`.

## Files that expose personal data (HIGH)
| Path | What | Count |
|---|---|---|
| agent/config/profile.json | name, personal email, phone, city/ZIP, LinkedIn, GitHub, visa status, rate | 1 file (all fields) |
| agent/resume.pdf | full resume (employers, dates, contact) | 1 file |
| agent/screenshots/*.png | browser screenshots of application forms (may show PII) | 111 files, several ~1.8 MB |
| manual_apply_list.html | generated list of jobs/links, 2 MB | 1 file |
| agent/data/vendor_list.json | recruiter/vendor emails | ~1930 email lines |
| agent/data/vendor_outreach_history.json (+ .bak2, .pre-gmail-backup) | recruiter emails + outreach log | ~860 / 103 / 83 |
| agent/data/nvoids_leads.json, recruiter_job_leads.json | recruiter emails and phones | ~494 / ~392 |
| agent/data/apollo_recruiter_candidates.json | recruiter emails | 8 |
| contacted.json, data/vendor_list.json, data/vendor_outreach_history.json | older copies of the same lists | 60 / 16 / 16 |
| RECRUITERS_TO_CALL.md, US_VENDORS_APPLY_LIST.md, OUTREACH_TEMPLATES.md, LOOPCV_SETUP.md | recruiter contacts, templates with phone/email | 33 / 1 / 2 / 1 |
| agent/data/dice_applied*.json, greenhouse_applied.json, applied_companies/jks/titles.json, linkedin_applied.json | job-search history (who you applied to) | 8 files |
| agent/data/cv_health*.json | internal metrics + alert state | 2 files |
| agent/SESSION_MEMORY.md, SESSION_2026-10-06_LEARNINGS.md | session notes, contacts | 8 email lines |

## Hard-coded PII in source (MEDIUM)
Phone/email literals in: agent/scripts/smart_reply_tracker.py (5), recruiter_auto_reply.py (5),
post_hotlist.py (2), outreach.py (2+6 emails), verify_email.py (6 emails), agent/scripts/vendor_outreach.py (22 emails),
vendor_portal_upload.py, recruiter_pipeline.py, rate_strategy.py, draft_hot_lead_replies.py, apollo_outreach.py,
agent/src/page_doctor.py, visual_analyzer.py, agent/Modelfile, agent/data/schema.sql, plus test fixtures
(agent/tests/*, test_deep_search.py ~41 emails - mostly fake/sample data; review).
Fixed in this PR: `agent/src/ai_fallback.py` (prompt now built from PROFILE_JSON secret / profile.json, test added)
and `linkedin_easy_apply.py` (defaults removed; uses GMAIL_USER / APPLICANT_PHONE / APPLICANT_EMAIL env).
Not touched (other agents are editing / needs runtime check): the scripts listed above.

## Recommendation
1. **Decision for the owner: make the repo private.** The recruiter lists (about 3,000 email lines), resume,
   profile and application history are public today. Trade-off: on a private repo `ubuntu-latest` Actions minutes
   are metered (free plan 2,000 min/month; cloud jobs here: solve-unsolved 12x/day, harvest 12x/day, hot-reply 48x/day,
   calendar alert, cv-health 24x/day, agent now cloud) while the self-hosted runner stays free. Cloud use is roughly
   1,000-1,500 min/day at current cron rates, so private + free plan would run out in 2-3 days; options: GitHub Pro
   (3,000 min), move more jobs to the self-hosted runner, or reduce cloud cron frequency (hot-reply-alerts every 30 min,
   calendar alert every 10 min, solve-unsolved).
2. If staying public: remove the HIGH files from the working tree, add them to `.gitignore`, and load them at run time:
   - profile.json -> repo secret `PROFILE_JSON` (code already reads it in ai_fallback.py; add the same for other readers).
   - resume.pdf -> secret `RESUME_B64`, decoded in the workflow step.
   - vendor/lead/applied JSON -> actions cache or a private data repo (checkout with a PAT) instead of git.
   - screenshots -> upload as workflow artifacts (short retention), `agent/screenshots/` in `.gitignore`.
3. Because git history keeps the old data, making the repo private (or history rewrite with `git filter-repo` plus
   key/contact rotation) is the only real fix. Rewrite was NOT done here (destructive). Rotate anything that was ever
   committed if in doubt (no live secret values were found).
4. Add a CI check (grep for phone/email patterns in tracked non-test files) to stop new leaks.
