#!/usr/bin/env python3
"""Dynamic knobs for the apply workflows (stdlib only, Python 3.8+ safe, never fails).

Reads agent/data/cv_dynamic.json (bounds) + agent/data/cv_health.json (real confirmed
counts written by cv-health.yml) and exports CV_<KNOB> env vars (to $GITHUB_ENV).
Workflows use:  ${{ env.CV_TARGET_SUBMITS || '15' }}  so defaults stay identical when
this script outputs nothing (file missing, stale health data, too little data, disabled).

Rule: scale = clamp(platform_share_of_7d_confirmed * n_platforms, scale_min, scale_max).
A platform with 0 confirmed in 7d gets the default (never hammer a broken platform).
Also exports CV_PLATFORM_PRIORITY (platforms ranked by 7d confirmed) for information.

Usage: python3 scripts/cv_dynamic.py --platform indeed
"""
import json, os, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")


def load(name):
    try:
        with open(os.path.join(DATA, name)) as f:
            return json.load(f)
    except Exception:
        return None


def emit(pairs):
    path = os.environ.get("GITHUB_ENV")
    lines = ["%s=%s" % (k, v) for k, v in pairs]
    for l in lines:
        print("cv_dynamic:", l)
    if path and lines:
        with open(path, "a") as f:
            f.write("\n".join(lines) + "\n")


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def main():
    plat = sys.argv[sys.argv.index("--platform") + 1] if "--platform" in sys.argv else ""
    cfg, health = load("cv_dynamic.json"), load("cv_health.json")
    if not cfg or not cfg.get("enabled") or not health or plat not in cfg.get("platforms", {}):
        print("cv_dynamic: using workflow defaults")
        return
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(health["generated_at"])).total_seconds() / 3600
    except Exception:
        age = 1e9
    if age > cfg.get("max_health_age_hours", 48):
        print("cv_dynamic: health data stale -> defaults")
        return
    counts = {p: int(v.get("confirmed_7d", 0)) for p, v in health.get("platforms", {}).items()}
    total = sum(counts.values())
    ranked = sorted(counts, key=lambda p: -counts[p])
    out = [("CV_PLATFORM_PRIORITY", ",".join(ranked))]
    if total >= cfg.get("min_total_confirmed_7d", 5) and counts.get(plat, 0) > 0:
        n = max(len(counts), 1)
        scale = clamp(counts[plat] / float(total) * n, cfg.get("scale_min", 0.7), cfg.get("scale_max", 1.5))
        for knob, b in cfg["platforms"][plat].items():
            val = int(round(clamp(b["default"] * scale, b["min"], b["max"])))
            out.append(("CV_" + knob, val))
        print("cv_dynamic: %s share=%d/%d scale=%.2f" % (plat, counts[plat], total, scale))
    else:
        print("cv_dynamic: not enough data for %s -> default knobs" % plat)
    emit(out)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never break the apply job
        print("cv_dynamic: ignored error", type(e).__name__)
