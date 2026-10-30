#!/usr/bin/env python3
"""Export the full vendor + recruiter list to MY_VENDOR_LIST.csv (openable in Excel/Numbers).

Columns: name, email, domain, notes, contacted (yes/no), times_contacted.
Gold named-recruiter leads (humans who emailed Bob) are marked source=gold-lead.

Run: cd ~/Downloads/CV/job-finder && python3 export_vendor_list.py
"""
import csv
import json
import os

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent", "data")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MY_VENDOR_LIST.csv")


def _load(name, default):
    p = os.path.join(BASE, name)
    try:
        return json.load(open(p))
    except Exception:
        return default


def main():
    vendors = _load("vendor_list.json", [])
    leads = _load("recruiter_job_leads.json", [])
    hist = _load("vendor_outreach_history.json", {})

    rows = []
    seen = set()

    # Gold named recruiters first (real humans who emailed Bob about Java roles)
    for r in (leads if isinstance(leads, list) else []):
        em = (r.get("recruiter_email") or "").strip().lower()
        if not em or em in seen:
            continue
        seen.add(em)
        h = hist.get(em, {})
        rows.append([r.get("recruiter_name") or r.get("company") or em, em,
                     em.split("@")[-1], "GOLD named recruiter (replied/emailed you)",
                     "yes" if h else "no", h.get("times_contacted", 0), "gold-lead"])

    # Then the full vendor list
    for v in (vendors if isinstance(vendors, list) else []):
        em = (v.get("email") or "").strip().lower()
        if not em or em in seen:
            continue
        seen.add(em)
        h = hist.get(em, {})
        rows.append([v.get("name", ""), em, v.get("domain", ""), v.get("notes", ""),
                     "yes" if h else "no", h.get("times_contacted", 0), "vendor"])

    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "email", "domain", "notes", "contacted",
                    "times_contacted", "source"])
        w.writerows(rows)

    contacted = sum(1 for r in rows if r[4] == "yes")
    print(f"✅ Wrote {OUT}")
    print(f"   {len(rows)} total  |  {len(leads)} gold recruiters  |  "
          f"{contacted} already contacted  |  {len(rows) - contacted} not yet")


if __name__ == "__main__":
    main()
