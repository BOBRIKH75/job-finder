#!/usr/bin/env python3
"""
Multi-source job discovery (NEW, additive — does not touch existing applier code).

Pulls fresh Java/Spring/C2C jobs from sources NOT covered by the existing
indeed/dice/greenhouse/linkedin appliers:
  - ZipRecruiter  (via jobspy — runs on CLOUD ubuntu runner to dodge the Cloudflare
                   403 that blocks it on the self-hosted/home runner)
  - Google Jobs   (via jobspy — aggregates many boards)
  - RemoteOK      (free public API)
  - We Work Remotely (public RSS)

Output: agent/data/discovered_jobs.json  (list of {title, company, url, source,
location, date, is_remote}). Deduped by url. Downstream steps:
  - harvest_boards_from_discovered.py  -> finds grnh.se/lever.co links -> companies.json
  - send_fresh_digest.py               -> emails Bob the new jobs with apply links

Safe: read-only against the web, write-only to its own data file. No applier touched.
Run: python scripts/discover_jobs_multi.py
"""
import json, os, re, ssl, sys, time
import urllib.request
from datetime import datetime
from pathlib import Path

# Tolerant SSL context (some runners lack full CA bundle; the sources are public).
try:
    _SSL = ssl.create_default_context()
except Exception:
    _SSL = None


def _get(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=_SSL).read().decode("utf-8", "replace")
    except Exception:
        # fallback: unverified context (public data, read-only)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return urllib.request.urlopen(req, timeout=timeout, context=ctx).read().decode("utf-8", "replace")

OUT = Path(__file__).parent.parent / "data" / "discovered_jobs.json"
TERMS = [
    "Java developer", "Senior Java developer", "Java Spring Boot",
    "Java backend developer", "Java microservices", "Spring Boot developer",
]
# CV match: must look Java/backend, skip obvious off-target
_POS = re.compile(r"\b(java|spring|backend|microservice|j2ee)\b", re.I)
_NEG = re.compile(r"\b(\.net|c#|salesforce|android|ios|nurse|data entry|php|golang|rust)\b", re.I)


def _match(title: str, desc: str = "") -> bool:
    t = f"{title} {desc}"
    return bool(_POS.search(t)) and not _NEG.search(title or "")


def from_jobspy() -> list:
    """ZipRecruiter + Google Jobs via jobspy. On a cloud runner ZipRecruiter's
    Cloudflare WAF usually does NOT 403 (home-IP runner does). Best-effort per site."""
    out = []
    try:
        from jobspy import scrape_jobs
    except Exception as e:
        print(f"  jobspy unavailable: {e}")
        return out
    for site in ("zip_recruiter", "google"):
        for term in TERMS[:4]:
            try:
                df = scrape_jobs(site_name=[site], search_term=term,
                                 google_search_term=f"{term} jobs remote contract",
                                 location="USA", results_wanted=25, hours_old=168)
            except Exception as e:
                print(f"  {site} '{term[:25]}' err: {str(e)[:50]}")
                continue
            if df is None or getattr(df, "empty", True):
                continue
            for _, r in df.iterrows():
                title = str(r.get("title", ""))
                if not _match(title, str(r.get("description", ""))):
                    continue
                url = str(r.get("job_url_direct") or r.get("job_url") or "")
                if not url or url in ("nan", "None"):
                    continue
                out.append({
                    "title": title, "company": str(r.get("company", "")),
                    "url": url, "source": site,
                    "location": str(r.get("location", "")),
                    "is_remote": bool(r.get("is_remote", False)),
                    "date": str(r.get("date_posted", "")),
                })
            time.sleep(2)
    print(f"  jobspy (zip+google): {len(out)} Java jobs")
    return out


def from_remoteok() -> list:
    out = []
    try:
        data = json.loads(_get("https://remoteok.com/api?tags=java"))
    except Exception as e:
        print(f"  RemoteOK err: {str(e)[:50]}")
        return out
    for j in data:
        if not isinstance(j, dict) or not j.get("position"):
            continue
        title = j.get("position", "")
        if not _match(title, " ".join(j.get("tags", []))):
            continue
        out.append({
            "title": title, "company": j.get("company", ""),
            "url": j.get("url") or j.get("apply_url", ""), "source": "remoteok",
            "location": j.get("location", "Remote"), "is_remote": True,
            "date": j.get("date", ""),
        })
    print(f"  RemoteOK: {len(out)} Java jobs")
    return out


def from_weworkremotely() -> list:
    out = []
    try:
        xml = _get("https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss")
    except Exception as e:
        print(f"  WWR err: {str(e)[:50]}")
        return out
    for m in re.finditer(r"<item>(.*?)</item>", xml, re.S):
        block = m.group(1)
        title = (re.search(r"<title>(.*?)</title>", block, re.S) or [None, ""])[1]
        link = (re.search(r"<link>(.*?)</link>", block, re.S) or [None, ""])[1]
        title = re.sub(r"<!\[CDATA\[|\]\]>", "", title).strip()
        if not _match(title):
            continue
        comp = title.split(":")[0].strip() if ":" in title else ""
        out.append({"title": title, "company": comp, "url": link.strip(),
                    "source": "weworkremotely", "location": "Remote",
                    "is_remote": True, "date": ""})
    print(f"  WeWorkRemotely: {len(out)} Java jobs")
    return out


def main():
    print(f"🔎 Multi-source discovery {datetime.utcnow().isoformat()}")
    found = []
    found += from_jobspy()
    found += from_remoteok()
    found += from_weworkremotely()

    # dedupe by url
    seen, uniq = set(), []
    for j in found:
        u = j["url"]
        if u and u not in seen:
            seen.add(u)
            uniq.append(j)

    # merge with existing (keep history, mark new)
    prev = []
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text())
        except Exception:
            prev = []
    prev_urls = {j.get("url") for j in prev}
    new_ones = [j for j in uniq if j["url"] not in prev_urls]
    for j in new_ones:
        j["first_seen"] = datetime.utcnow().isoformat()

    merged = (new_ones + prev)[:1000]   # cap file size
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(merged, indent=2))
    print(f"\n✅ {len(uniq)} unique Java jobs this run · {len(new_ones)} NEW · "
          f"{len(merged)} total tracked -> {OUT.name}")


if __name__ == "__main__":
    main()
