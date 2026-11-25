"""Keep automation Chrome out of the user's way on a shared laptop.

The runner laptop is also Bob's daily machine. Headful Chrome is required (sites block
headless), but its windows must not cover his work. With CV_QUIET_WINDOW=1 (default):
  - every automation window is minimized right after it opens (CDP Browser.setWindowBounds),
  - background/occlusion throttling is disabled so a minimized page still runs at full speed,
  - a fixed viewport is used so layout does not depend on the (minimized) window size.
Set CV_QUIET_WINDOW=0 to watch the bot work.
"""
import os

QUIET_ARGS = [
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--no-first-run",
    "--no-default-browser-check",
]
VIEWPORT = {"width": 1366, "height": 900}


def enabled() -> bool:
    return os.environ.get("CV_QUIET_WINDOW", "1") == "1"


def apply_launch_kwargs(kw: dict) -> dict:
    """Add quiet-mode options to Playwright launch kwargs (returns the same dict)."""
    if not enabled() or kw.get("headless"):
        return kw
    kw["args"] = list(kw.get("args") or []) + [a for a in QUIET_ARGS if a not in (kw.get("args") or [])]
    if kw.pop("no_viewport", None):
        kw["viewport"] = VIEWPORT
    return kw


def _minimize(page) -> None:
    try:
        cdp = page.context.new_cdp_session(page)
        win = cdp.send("Browser.getWindowForTarget")["windowId"]
        cdp.send("Browser.setWindowBounds", {"windowId": win, "bounds": {"windowState": "minimized"}})
        cdp.detach()
    except Exception:
        pass  # never break a run over window management


def quiet_context(ctx):
    """Minimize current and future pages of a context (no-op when disabled)."""
    if not enabled():
        return ctx
    for page in list(ctx.pages):
        _minimize(page)
    ctx.on("page", _minimize)
    return ctx
