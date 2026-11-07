"""Ashby job-board scanner (public posting API) for the same company slugs we use for Greenhouse.

Returns CV-fit, US/remote, fresh jobs shaped like the Greenhouse scan so the SAME browser engine
(applier.run_applications) can apply. Read-only; never raises."""
import re
import concurrent.futures as cf
from datetime import datetime, timezone, timedelta

import requests

_API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def _fetch(slug):
    try:
        r = requests.get(_API.format(slug=slug), timeout=10)
        if r.status_code != 200:
            return slug, []
        return slug, r.json().get("jobs", []) or []
    except Exception:
        return slug, []


def _fresh(published, max_age_days):
    try:
        when = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - when <= timedelta(days=max_age_days)
    except Exception:
        return True   # unknown date -> let the other gates decide


def scan_ashby(slugs, cv_ok, non_us, title_block, max_age_days=14, workers=12):
    """cv_ok(title, desc, loc)->(ok, score, why); non_us(loc)->bool; title_block: compiled regex."""
    out = []
    with cf.ThreadPoolExecutor(workers) as ex:
        for slug, jobs in ex.map(_fetch, sorted(set(s.lower() for s in slugs))):
            for j in jobs:
                if j.get("isListed") is False:
                    continue
                title = j.get("title", "") or ""
                loc = j.get("location", "") or ""
                wt = (j.get("workplaceType") or "").strip().lower()
                remote = (wt == "remote") if wt else bool(j.get("isRemote"))
                url = j.get("applyUrl") or j.get("jobUrl") or ""
                if not url or title_block.search(title) or not _fresh(j.get("publishedAt"), max_age_days):
                    continue
                if not remote:      # Bob is remote-only (no relocation): on-site Ashby roles are skipped
                    continue
                if non_us(loc) and not (remote and re.search(r"united states|\bus\b|usa|americas|north america", loc, re.I)):
                    continue
                ok, score, _ = cv_ok(title, (j.get("descriptionPlain") or "")[:6000], loc)
                if not ok:
                    continue
                out.append({"url": url, "title": title, "company": slug, "location": loc,
                            "remote": remote, "score": score, "ats_type": "ashby"})
    return out
