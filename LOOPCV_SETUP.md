# 🔄 LoopCV Setup — zero-maintenance auto-apply to 30+ boards (one-time, ~20 min)

**Why:** LoopCV is a cloud auto-apply agent that runs on its OWN servers (no laptop,
no CI/CD to maintain). It applies continuously across 30+ job boards + does recruiter
email outreach. It covers boards your bot can't (ZipRecruiter, Glassdoor, etc. that
Cloudflare blocks for us). You already have an account linked to bobrikh75@gmail.com
(per /cv skill). This is ADDITIONAL coverage — runs alongside the bot, nothing to break.

## Setup steps
1. Log in: https://loopcv.pro  (account: bobrikh75@gmail.com)
2. Upload CV: `Bob_Rikh_Java_Backend_Developer_C2C.pdf` (from ~/Downloads/CV/).
3. Create a "Loop" (search config) — make 2-3 loops to cover variations:

   **Loop 1 — Java C2C Remote**
   - Job titles: Java Developer, Senior Java Developer, Java Backend Developer, Spring Boot Developer
   - Keywords: Java, Spring Boot, Microservices, AWS, Kafka
   - Location: United States · Remote
   - Job type: Contract
   - Boards: enable ALL available (Indeed, LinkedIn, ZipRecruiter, Glassdoor, Dice, Monster, SimplyHired, etc.)

   **Loop 2 — Senior Java Engineer**
   - Titles: Senior Software Engineer Java, Java Software Engineer, Backend Engineer Java
   - same keywords/location/boards

   **Loop 3 — Spring/Microservices**
   - Titles: Spring Boot Developer, Java Microservices Developer, Java REST API Developer

4. Turn ON **Auto-Apply** for each loop (Settings → Auto-apply = ON).
5. Turn ON **Recruiter Outreach** (LoopCV emails recruiters it finds — extra channel).
6. Set **daily apply limit** to max on the free plan (upgrade later if conversion is good).
7. Answers/profile: Green Card (no sponsorship), C2C, $70-90/hr, Parker CO, 347-268-5917.

## What it does after setup
- Runs 24/7 on LoopCV's servers — finds matching jobs, auto-applies, emails recruiters.
- Sends you a daily report of what it applied to.
- Zero maintenance — no laptop, no CI/CD, no Cloudflare fights (it's their infra).

## Why this complements the bot
| Channel | Who runs it | Covers |
|---|---|---|
| Your bot (Dice/Greenhouse) | your laptop + GitHub | Dice easy-apply, Greenhouse API |
| discover-jobs.yml | GitHub cloud | RemoteOK, WWR + digest email |
| **LoopCV** | LoopCV servers | **30+ boards incl. ZipRecruiter/Glassdoor the bot can't reach** |
| Hotlist | GitHub cloud | 43 C2C vendor groups |
| Outreach | GitHub cloud | named recruiters |

LoopCV fills the exact gap (ZipRecruiter/Glassdoor/Monster) that Cloudflare blocks our bot from — without us maintaining anything.
