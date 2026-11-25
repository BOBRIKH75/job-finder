import importlib.util, os
from datetime import datetime, timedelta
_p = os.path.join(os.path.dirname(__file__), "..", "..", "greenhouse_apply.py")
_s = importlib.util.spec_from_file_location("gha", _p); g = importlib.util.module_from_spec(_s); _s.loader.exec_module(g)


def test_company_count_window_and_case():
    now = datetime(2026, 11, 25)
    ap = {"squarespace|software engineer": now.isoformat(),
          "squarespace|backend engineer": (now - timedelta(days=2)).isoformat(),
          "squarespace|java dev": "2000-01-01T00:00:00",
          "squarespace inc|x": now.isoformat()}
    assert g._company_applied_count(ap, "Squarespace", now) == 2
    assert g._company_applied_count(ap, "", now) == 0
    assert g._company_applied_count(ap, "Canonical", now) == 0
