# Runner & Cookie Setup (any laptop)

This repo's apply jobs for **Dice / Indeed / LinkedIn** require a **self-hosted GitHub Actions
runner** on a machine with a residential IP, because those sites bind the login session to the IP
(a cloud runner IP breaks the session instantly). Greenhouse + vendor/recruiter workflows run on
`ubuntu-latest` (cloud) and need no local runner.

Everything machine-local (runner registration, cookies, secrets) is intentionally NOT in git.
This doc is the behavior any new laptop follows to get working.

## 1. Install the self-hosted runner

```bash
# download the runner from the repo's Settings → Actions → Runners → New self-hosted runner
# then, in the runner folder:
./config.sh --url https://github.com/BOBRIKH75/job-finder \
  --token <REGISTRATION_TOKEN> \
  --name "$(hostname)-runner" \
  --labels self-hosted,macOS,ARM64,linkedin \
  --unattended --replace

# install as a service so it AUTO-STARTS on login (critical — if it dies, nothing applies)
./svc.sh install
./svc.sh start
./svc.sh status      # must show "Listening for Jobs"
```

Get the registration token (needs repo admin on BOBRIKH75/job-finder):

```bash
gh api -X POST repos/BOBRIKH75/job-finder/actions/runners/registration-token -q .token
```

### If the runner was offline a long time
GitHub deletes the registration for runners that haven't connected recently. Symptom in the log:
`Failed to create a session. The runner registration has been deleted`. Fix = re-register:

```bash
./svc.sh stop && ./svc.sh uninstall
./config.sh remove --token $(gh api -X POST repos/BOBRIKH75/job-finder/actions/runners/remove-token -q .token)
./config.sh --url https://github.com/BOBRIKH75/job-finder \
  --token $(gh api -X POST repos/BOBRIKH75/job-finder/actions/runners/registration-token -q .token) \
  --name "$(hostname)-runner" --labels self-hosted,macOS,ARM64,linkedin --unattended --replace
./svc.sh install && ./svc.sh start
```

## 2. Cookies / sign-in (per laptop, never committed)

| Platform | How the bot signs in | Refresh |
|----------|----------------------|---------|
| **Dice** | persistent `agent/.dice-profile` (bot's own Chrome profile) | `refresh-dice-cookies.yml` reads the profile, sets `DICE_COOKIES` secret. One-time local login: run with `DICE_MANUAL_LOGIN=1`. |
| **Indeed** | `agent/data/indeed_cookies.json` (gitignored) | `save_indeed_cookies.py` from local Chrome; IP-bound. |
| **LinkedIn** | `LINKEDIN_COOKIES` secret | see below — macOS encrypts Chrome cookies, so auto-extract fails; set manually. |

### LinkedIn one-time manual cookie (macOS Chrome encrypts cookies → auto-read fails)
1. Chrome → linkedin.com → make sure you're logged in.
2. F12 → Application → Cookies → `https://www.linkedin.com`.
3. Copy the **Value** of `li_at` and `JSESSIONID`.
4. Set the secret:
   ```bash
   gh secret set LINKEDIN_COOKIES --repo BOBRIKH75/job-finder \
     --body 'li_at=<VALUE>; JSESSIONID=<VALUE>'
   ```

## 3. Email confirmation of real submits
The apply jobs run `check_*_confirmations.py` to verify submits via Gmail. They need these secrets
(and the runner `.env`): `GMAIL_USER`, `GMAIL_APP_PASSWORD`. If missing, the log shows
`no gmail creds` and confirmation is skipped (applies still happen, just unverified by email).

## 4. Real application count (do NOT trust job_applications.csv — it's empty)
```bash
cd ~/Downloads/CV && python3 -c "import json;d=lambda p:len(json.load(open(p)));print('TOTAL',d('job-finder/agent/data/dice_applied.json')+d('job-finder/agent/data/greenhouse_applied.json')+d('job-finder/linkedin_applied.json'))"
```

## 5. Health check (is anything actually running?)
```bash
./svc.sh status                                  # runner alive?
gh run list --repo BOBRIKH75/job-finder --limit 5   # recent job results
tail -5 runner-live.log                           # last job activity date
```
If the last activity is not recent, the runner is down → no applications are going out.
