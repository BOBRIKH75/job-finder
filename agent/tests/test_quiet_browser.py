import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src import quiet_browser as q


def test_quiet_adds_args_and_fixed_viewport(monkeypatch):
    monkeypatch.setenv("CV_QUIET_WINDOW", "1")
    kw = q.apply_launch_kwargs({"headless": False, "no_viewport": True, "args": ["--x"]})
    assert "--disable-backgrounding-occluded-windows" in kw["args"] and "--x" in kw["args"]
    assert kw["viewport"] == q.VIEWPORT and "no_viewport" not in kw


def test_quiet_off_or_headless_leaves_kwargs(monkeypatch):
    monkeypatch.setenv("CV_QUIET_WINDOW", "0")
    assert q.apply_launch_kwargs({"headless": False, "no_viewport": True}) == {"headless": False, "no_viewport": True}
    monkeypatch.setenv("CV_QUIET_WINDOW", "1")
    assert q.apply_launch_kwargs({"headless": True}) == {"headless": True}


def test_quiet_context_never_raises(monkeypatch):
    monkeypatch.setenv("CV_QUIET_WINDOW", "1")
    class Ctx:
        pages = [object()]
        def on(self, ev, fn): self.ev = ev
    c = q.quiet_context(Ctx())
    assert c.ev == "page"
