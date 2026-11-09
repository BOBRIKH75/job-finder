# Things the bot cannot answer truthfully yet (please add to agent/config/profile.json)

The bot only answers from `agent/config/profile.json`. When a required question has no
truthful answer, it skips that job instead of guessing. These gaps came from real runs:

| Missing info | Seen in | Suggested profile key |
|---|---|---|
| Street address (Address Line 1) | LinkedIn Easy Apply contact form | `address_line1` |
| Work on W2 (yes/no)? Currently only C2C is on record | LinkedIn "Can you work on W2?" | `open_to_w2` |
| ~~Willing to relocate?~~ DONE: No (`willing_to_relocate=false`) | Indeed + LinkedIn | `willing_to_relocate` |
| ~~On-site / hybrid?~~ DONE: Denver metro / Colorado only (searches now include Denver) | Indeed + LinkedIn + Dice | `open_to_onsite`, `onsite_locations` |
| ~~In-person interviews?~~ DONE: Denver metro only | LinkedIn | `in_person_interview_ok` |
| ~~Start year of current job~~ DONE: 2024 (Spectrum/Charter, from CV) | Indeed | `current_job_start_year` |
| Graduation year | Indeed | `graduation_year` |
| Self-rated skill levels / years per technology (big data, system design, etc.) | LinkedIn dropdowns | `skill_years: {"kafka": 6, ...}` |
| Domain experience years (banking, order management, ...) - now answered 0 | LinkedIn / Indeed | `domain_years: {...}` |

Until these exist, the bot answers "No" / "0" (truthful default) or skips the job.

## Open issues found in round 3 (not blocked on you, but worth knowing)

- LinkedIn sends no "Your application was sent" email to the Gmail the bot reads (0 in 24h),
  even when the job page afterwards shows an "Application status" card. Check that LinkedIn
  job-application emails are enabled for the Gmail inbox the bot reads (LinkedIn > Settings >
  Notifications > Job seeking).
- Before the fix in this round, LinkedIn job 4478570438 (Seattle area) got "Yes" to
  "comfortable commuting to this job's location". That is now fixed: we answer "No" unless the
  place named is in Colorado / the US in general. Withdraw that one by hand if you want.
- Some LinkedIn forms loop on "Review" with no error shown (jobs 4485827936, 4487008372). Needs one
  more debug run.
