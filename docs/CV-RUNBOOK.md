# CV Job-Finder Runbook (one page)

## How it works
- **Cloud** (no Mac needed): Greenhouse apply, Gmail checks, alerts, and the health report.
- **Other Mac** (runner `bobur-laptop`): Indeed, Dice, LinkedIn apply. They wait in line if the Mac is asleep/offline.
- **cv-health** runs every hour. It counts REAL applications from Gmail confirmation emails and writes `agent/data/cv_health.json`.
  The apply jobs read it and adjust their size (`agent/data/cv_dynamic.json`, safe min/max).

## You get a phone alert (ntfy) when
| Alert | Meaning | What to do |
|---|---|---|
| CV runner OFFLINE | Other Mac off/asleep > 2h | Step A below |
| CV <platform>: 0 confirmed | No confirmation email in 24h (LinkedIn: 48h) | Open the latest run of that workflow; if cookies -> Step C |
| CV <platform> cookie/session expired | Run log shows login/cookie expiry | Step C |
Each alert repeats at most once every 12h, and clears itself when fixed.

## A. Runner is offline (on the OTHER Mac)
1. Open Terminal, go to the job-finder folder: `cd ~/Downloads/CV/job-finder && git pull`
2. `bash scripts/runner-doctor.sh`  (it fixes what is safe and tells you the rest)
3. If it says "no configured runner": `bash fix-runner.sh`
4. Check: GitHub repo -> Settings -> Actions -> Runners shows **bobur-laptop = Idle/Active**.

## B. One-time setup on the other Mac (keeps it online)
1. `bash scripts/runner-doctor.sh --install-keepalive`  (watchdog every 10 min + caffeinate)
2. Copy/paste the `sudo pmset ...` line it prints (stops system sleep). Keep the Mac plugged in, lid open or on a display.
3. Needs: Python 3.10+ (`brew install python@3.12`), Google Chrome.

## C. Cookies / login expired
1. Log in again in Chrome on the other Mac (Indeed / Dice / LinkedIn).
2. Run the matching workflow: Actions -> *Refresh ... cookies* -> Run workflow (or update the secret `INDEED_COOKIES` / `DICE_COOKIES` / `LINKEDIN_COOKIES` in repo Settings -> Secrets).
3. Run the apply workflow once (Actions -> Run workflow). The next cv-health run (within 1 hour) clears the alert if it worked.

## D. Check results any time
- Actions -> **CV Health** -> latest run -> *Summary* table (confirmed 24h / 7d per platform, last success, runner).
- Or open `agent/data/cv_health.json` in the repo.

## E. Tune
- `agent/data/cv_dynamic.json`: change `min`/`max`/`default` per knob, or set `"enabled": false` to use the fixed workflow values.
- Schedules: Indeed = even hours `:00`, Dice = odd hours `:30`, Greenhouse = even hours `:15` (cloud). The single runner runs one job at a time; each workflow queues its own next run (never cancels a running one).
