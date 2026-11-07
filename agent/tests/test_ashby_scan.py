import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import src.ashby_scan as ash  # noqa: E402
import re  # noqa: E402


def _job(**kw):
    base = {"title": "Senior Backend Engineer", "location": "United States", "isListed": True,
            "workplaceType": "Remote", "applyUrl": "https://jobs.ashbyhq.com/x/1/application",
            "publishedAt": "2999-01-01T00:00:00+00:00", "descriptionPlain": "java spring"}
    base.update(kw)
    return base


def _scan(jobs, monkeypatch):
    monkeypatch.setattr(ash, "_fetch", lambda slug: (slug, jobs))
    return ash.scan_ashby(["x"], lambda t, d, l: (True, 5, []), lambda l: "europe" in l.lower(),
                          re.compile(r"manager", re.I), workers=1)


def test_remote_us_job_kept(monkeypatch):
    assert len(_scan([_job()], monkeypatch)) == 1


def test_onsite_and_hybrid_skipped(monkeypatch):
    assert _scan([_job(workplaceType="Hybrid"), _job(workplaceType="OnSite")], monkeypatch) == []


def test_non_us_remote_skipped_but_us_mention_kept(monkeypatch):
    assert _scan([_job(location="Europe")], monkeypatch) == []
    assert len(_scan([_job(location="Europe or US")], monkeypatch)) == 1


def test_blocked_title_skipped(monkeypatch):
    assert _scan([_job(title="Engineering Manager")], monkeypatch) == []
