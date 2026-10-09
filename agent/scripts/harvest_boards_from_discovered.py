#!/usr/bin/env python3
"""
Harvest Greenhouse/Lever boards from discovered_jobs.json → companies.json (NEW, additive).

Many jobs found by discover_jobs_multi.py (RemoteOK/WWR/ZipRecruiter) apply via
Greenhouse (grnh.se / boards.greenhouse.io / job-boards.greenhouse.io) or Lever
(jobs.lever.co). Those are exactly what the EXISTING greenhouse applier can submit.
This script extracts those board tokens, VERIFIES each has a live board (HTTP 200),
and appends new ones to companies.json. Turns 'discovered' jobs into real applies
through the working channel. Touches only companies.json (adds entries, never removes).

Run: python scripts/harvest_boards_from_discovered.py
"""
import json, re, ssl, urllib.request
from pathlib import Path

DISC = Path(__file__).parent.parent / "data" / "discovered_jobs.json"
COMP = Path(__file__).parent.parent / "data" / "companies.json"

_GH_RE = re.compile(r"(?:boards|job-boards)\.greenhouse\.io/([a-z0-9_-]+)", re.I)
_GRNH_RE = re.compile(r"grnh\.se/\w+", re.I)
_LEVER_RE = re.compile(r"jobs\.lever\.co/([a-z0-9_-]+)", re.I)


def _ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _resolve(url: str) -> str:
    """Follow a grnh.se short link to its final boards.greenhouse.io URL."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15, context=_ctx())
        return resp.geturl()
    except Exception:
        return url


def _verify_gh(token: str) -> bool:
    try:
        req = urllib.request.Request(
            f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
            headers={"User-Agent": "Mozilla/5.0"})
        return urllib.request.urlopen(req, timeout=12, context=_ctx()).status == 200
    except Exception:
        return False


def _verify_lever(token: str) -> bool:
    try:
        req = urllib.request.Request(
            f"https://api.lever.co/v0/postings/{token}?limit=1",
            headers={"User-Agent": "Mozilla/5.0"})
        return urllib.request.urlopen(req, timeout=12, context=_ctx()).status == 200
    except Exception:
        return False


def main():
    if not DISC.exists():
        print("no discovered_jobs.json yet — run discover_jobs_multi.py first")
        return
    jobs = json.loads(DISC.read_text())
    gh_tokens, lever_tokens = set(), set()

    for j in jobs:
        url = j.get("url", "") or ""
        if _GRNH_RE.search(url):
            url = _resolve(url)
        m = _GH_RE.search(url)
        if m:
            gh_tokens.add(m.group(1).lower())
        ml = _LEVER_RE.search(url)
        if ml:
            lever_tokens.add(ml.group(1).lower())

    print(f"candidate boards from discovered jobs: {len(gh_tokens)} greenhouse, {len(lever_tokens)} lever")

    comp = json.loads(COMP.read_text())
    comp.setdefault("greenhouse", [])
    comp.setdefault("lever", [])
    gh_before, lev_before = len(comp["greenhouse"]), len(comp["lever"])

    added_gh, added_lv = [], []
    for t in sorted(gh_tokens):
        if t not in comp["greenhouse"] and _verify_gh(t):
            comp["greenhouse"].append(t); added_gh.append(t)
    for t in sorted(lever_tokens):
        if t not in comp["lever"] and _verify_lever(t):
            comp["lever"].append(t); added_lv.append(t)

    comp["greenhouse"] = sorted(set(comp["greenhouse"]))
    comp["lever"] = sorted(set(comp["lever"]))
    COMP.write_text(json.dumps(comp, indent=2))

    print(f"greenhouse {gh_before} -> {len(comp['greenhouse'])} (added {added_gh})")
    print(f"lever {lev_before} -> {len(comp['lever'])} (added {added_lv})")
    print(f"✅ {len(added_gh)+len(added_lv)} new verified boards -> greenhouse applier will apply to them")


if __name__ == "__main__":
    main()
