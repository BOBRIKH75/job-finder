#!/usr/bin/env python3
"""CV pipeline health: truthful metrics + de-duplicated phone alerts (cloud job, stdlib + gh CLI).

Writes agent/data/cv_health.json (report) and agent/data/cv_health_alerts.json (alert dedup).
Real application counts come from Gmail confirmation emails (same sources/markers as
verify_real_applications.py). Alerts go through ntfy (same mechanism as alert_hot_replies.py).
Never prints secrets / full emails / log lines.

Env: GMAIL_USER, GMAIL_APP_PASSWORD, NTFY_TOPIC, GH_TOKEN, GITHUB_REPOSITORY
"""
import email, imaplib, json, os, re, subprocess, sys, time, urllib.request
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.utils import parsedate_to_datetime

REPO = os.environ.get("GITHUB_REPOSITORY", "BOBRIKH75/job-finder")
DATA = "data" if os.path.isdir("data") else "agent/data"
REPORT, STATE = os.path.join(DATA, "cv_health.json"), os.path.join(DATA, "cv_health_alerts.json")
NOW = datetime.now(timezone.utc)
RUNNER_OFFLINE_HOURS = 2
ALERT_COOLDOWN_H = 12
SELF_HOSTED = {"indeed", "dice", "linkedin"}          # need the laptop runner
ZERO_WINDOW_H = {"indeed": 24, "dice": 24, "greenhouse": 24, "linkedin": 48}  # linkedin runs ~1x/day
WORKFLOWS = {"indeed": "indeed-apply.yml", "dice": "dice-apply.yml",
             "greenhouse": "greenhouse-apply.yml", "linkedin": "linkedin-apply.yml"}
SOURCES = {  # same markers as verify_real_applications.py
    "dice": ('(FROM "applyonline@dice.com")', ("application for", "sent", "submitted", "received")),
    "indeed": ('(FROM "indeed.com")', ("application submitted", "you applied", "application was submitted",
                                       "has been submitted", "application sent")),
    "linkedin": ('(FROM "jobs-noreply@linkedin.com")', ("your application was sent", "application was sent", "you applied")),
    "greenhouse": ('(OR SUBJECT "thank you for applying" SUBJECT "application received")',
                   ("thank you for applying", "application received", "we received your application", "successfully submitted")),
}
EXPIRY_RE = re.compile(r"cookies?\W{0,20}(have |has |are |is )?(expired|invalid|stale)|session\W{0,15}expired|"
                       r"not logged in|login (wall|required)|redirected to (the )?login|please log ?in|"
                       r"cookie.{0,20}(dead|rejected)", re.I)


def gh(*args, timeout=120):
    try:
        r = subprocess.run(["gh"] + list(args), capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def gh_json(path):
    out = gh("api", path)
    try:
        return json.loads(out)
    except Exception:
        return None


def load(p, default):
    try:
        return json.load(open(p))
    except Exception:
        return default


def dec(s):
    return "".join(t.decode(e or "utf-8", "ignore") if isinstance(t, bytes) else t for t, e in decode_header(s or ""))


def gmail_counts():
    """-> {platform: {confirmed_24h, confirmed_7d}} or None if Gmail unavailable."""
    user, pw = os.environ.get("GMAIL_USER", ""), os.environ.get("GMAIL_APP_PASSWORD", "")
    if not user or not pw:
        return None
    try:
        M = imaplib.IMAP4_SSL("imap.gmail.com")
        M.login(user, pw)
        try:
            M.select('"[Gmail]/All Mail"', readonly=True)
        except Exception:
            M.select("inbox", readonly=True)
    except Exception:
        return None
    since = (NOW - timedelta(days=8)).strftime("%d-%b-%Y")
    res = {}
    for plat, (query, markers) in SOURCES.items():
        c24 = c7 = 0
        try:
            _, data = M.search(None, '(SINCE "%s") %s' % (since, query))
            ids = data[0].split() if data and data[0] else []
        except Exception:
            ids = []
        for i in ids[-400:]:
            try:
                _, md = M.fetch(i, "(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE)])")
                m = email.message_from_string(md[0][1].decode("utf-8", "ignore"))
                when = parsedate_to_datetime(m.get("Date"))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if not any(mk in dec(m.get("Subject")).lower() for mk in markers):
                continue
            age = NOW - when
            if age <= timedelta(days=7):
                c7 += 1
            if age <= timedelta(hours=24):
                c24 += 1
        res[plat] = {"confirmed_24h": c24, "confirmed_7d": c7}
    try:
        M.logout()
    except Exception:
        pass
    return res


def runner_info():
    d = gh_json("repos/%s/actions/runners" % REPO)
    if not d or "runners" not in d:
        return {"status": "unknown", "busy": None}
    rs = d["runners"]
    if not rs:
        return {"status": "none-registered", "busy": None}
    online = [r for r in rs if r.get("status") == "online"]
    return {"status": "online" if online else "offline", "busy": any(r.get("busy") for r in online) if online else None}


def workflow_info(plat):
    f = WORKFLOWS[plat]
    out = {"last_success": None, "last_run": None, "last_conclusion": None, "expiry_detected": False}
    d = gh_json("repos/%s/actions/workflows/%s/runs?status=success&per_page=1" % (REPO, f))
    if d and d.get("workflow_runs"):
        out["last_success"] = d["workflow_runs"][0]["updated_at"]
    d = gh_json("repos/%s/actions/workflows/%s/runs?per_page=5&exclude_pull_requests=true" % (REPO, f))
    runs = [r for r in (d or {}).get("workflow_runs", []) if r.get("status") == "completed" and r.get("conclusion") != "cancelled"]
    if runs:
        out["last_run"], out["last_conclusion"] = runs[0]["updated_at"], runs[0]["conclusion"]
        log = gh("run", "view", str(runs[0]["id"]), "--repo", REPO, "--log", timeout=150)
        if EXPIRY_RE.search(log[:3_000_000]):
            out["expiry_detected"] = True
    return out


def ntfy(title, body, priority="high", tags="warning"):
    topic = os.environ.get("NTFY_TOPIC", "")
    if not topic:
        return False
    try:
        req = urllib.request.Request("https://ntfy.sh/" + topic, data=body.encode("utf-8"), method="POST",
                                     headers={"Title": title.encode("ascii", "ignore").decode(), "Priority": priority, "Tags": tags})
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        return False


def main():
    state = load(STATE, {})
    alerts_sent = state.setdefault("alerts", {})
    runner = runner_info()
    # ---- runner offline tracking (API has no 'offline since', so remember last time seen online)
    if runner["status"] == "online" or not state.get("runner_last_online"):
        state["runner_last_online"] = NOW.isoformat()
    offline_h = (NOW - datetime.fromisoformat(state["runner_last_online"])).total_seconds() / 3600
    runner["offline_hours"] = round(offline_h, 1) if runner["status"] in ("offline", "none-registered") else 0

    counts = gmail_counts()
    platforms = {}
    for p in WORKFLOWS:
        platforms[p] = dict(workflow_info(p))
        platforms[p].update(counts[p] if counts else {"confirmed_24h": None, "confirmed_7d": None})

    problems = []  # (key, title, body)
    if runner["status"] in ("offline", "none-registered") and offline_h > RUNNER_OFFLINE_HOURS:
        problems.append(("runner_offline", "CV runner OFFLINE", "bobur-laptop runner offline ~%.0fh. Indeed/Dice/LinkedIn jobs are queued. Wake the other Mac / run scripts/runner-doctor.sh" % offline_h))
    runner_down = runner["status"] != "online"
    for p, v in platforms.items():
        if v["expiry_detected"]:
            problems.append(("expiry_" + p, "CV %s cookie/session expired" % p, "%s run log shows cookie/session expiry. Refresh the %s cookies secret." % (p, p)))
        if counts is None or v["confirmed_24h"] is None:
            continue
        # zero-confirmed check: skip when it is explained by the runner being down
        if p in SELF_HOSTED and runner_down:
            continue
        if ZERO_WINDOW_H[p] == 24:
            zero = v["confirmed_24h"] == 0
        else:  # wider window: need 7d counts + recent evidence; approximate using 7d-rate
            zero = v["confirmed_24h"] == 0 and v["confirmed_7d"] <= max(0, ZERO_WINDOW_H[p] // 24 - 1)
        if zero:
            problems.append(("zero_" + p, "CV %s: 0 confirmed in %dh" % (p, ZERO_WINDOW_H[p]),
                             "No confirmation emails for %s in %dh (7d total: %s). Check the workflow run + cookies." % (p, ZERO_WINDOW_H[p], v["confirmed_7d"])))
    # ---- dedup + send
    sent, suppressed = [], []
    for key, title, body in problems:
        last = alerts_sent.get(key)
        if last and (NOW - datetime.fromisoformat(last)).total_seconds() < ALERT_COOLDOWN_H * 3600:
            suppressed.append(key)
            continue
        if ntfy(title, body):
            alerts_sent[key] = NOW.isoformat()
            sent.append(key)
        else:
            suppressed.append(key + "(ntfy-not-sent)")
    active = {k for k, _, _ in problems}
    for k in list(alerts_sent):  # forget resolved problems so a recurrence alerts again
        if k not in active:
            del alerts_sent[k]

    report = {"generated_at": NOW.isoformat(), "runner": runner, "platforms": platforms,
              "gmail_ok": counts is not None,
              "total_confirmed_24h": sum(v["confirmed_24h"] or 0 for v in platforms.values()),
              "total_confirmed_7d": sum(v["confirmed_7d"] or 0 for v in platforms.values()),
              "problems": [k for k, _, _ in problems], "alerts_sent": sent, "alerts_suppressed": suppressed}
    json.dump(report, open(REPORT, "w"), indent=2)
    json.dump(state, open(STATE, "w"), indent=2)

    lines = ["## CV pipeline health (%s)" % NOW.strftime("%Y-%m-%d %H:%M UTC"), "",
             "Runner: **%s**%s" % (runner["status"], " (busy)" if runner.get("busy") else ""), "",
             "| Platform | Real confirmed 24h | 7d | Last success | Last run | Expiry? |", "|---|---|---|---|---|---|"]
    for p, v in platforms.items():
        lines.append("| %s | %s | %s | %s | %s | %s |" % (p, v["confirmed_24h"], v["confirmed_7d"], v["last_success"] or "-",
                                                      v["last_conclusion"] or "-", "YES" if v["expiry_detected"] else "no"))
    lines += ["", "Total real confirmed: %s (24h) / %s (7d)" % (report["total_confirmed_24h"], report["total_confirmed_7d"]),
              "Problems: %s | alerts sent: %s | suppressed(dedup): %s" % (report["problems"] or "none", sent or "none", suppressed or "none")]
    if counts is None:
        lines.append("WARNING: Gmail unavailable - counts are null (not zero).")
    md = "\n".join(lines)
    print(md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write(md + "\n")


if __name__ == "__main__":
    main()
