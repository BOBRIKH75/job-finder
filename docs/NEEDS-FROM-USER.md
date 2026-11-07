# Things the bot cannot answer truthfully yet (please add to agent/config/profile.json)

The bot only answers from `agent/config/profile.json`. When a required question has no
truthful answer, it skips that job instead of guessing. These gaps came from real runs:

| Missing info | Seen in | Suggested profile key |
|---|---|---|
| Street address (Address Line 1) | LinkedIn Easy Apply contact form | `address_line1` |
| Work on W2 (yes/no)? Currently only C2C is on record | LinkedIn "Can you work on W2?" | `open_to_w2` |
| Willing to relocate? (now always answered "No") | Indeed + LinkedIn | `willing_to_relocate` |
| Willing to work on-site / hybrid / commute outside Colorado? (now "No") | Indeed + LinkedIn | `open_to_onsite`, `onsite_locations` |
| Willing to attend in-person interviews in other cities? | LinkedIn | `in_person_interview_ok` |
| Start year of your most recent job (Indeed/Infosys form blocks without it) | Indeed | `current_job_start_year` |
| Graduation year | Indeed | `graduation_year` |
| Self-rated skill levels / years per technology (big data, system design, etc.) | LinkedIn dropdowns | `skill_years: {"kafka": 6, ...}` |
| Domain experience years (banking, order management, ...) - now answered 0 | LinkedIn / Indeed | `domain_years: {...}` |

Until these exist, the bot answers "No" / "0" (truthful default) or skips the job.
