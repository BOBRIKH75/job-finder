"""Failure skip lists must EXPIRE by reason (transient fails retry; login_redirect never blocks)."""
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import dice_apply as d


def test_reason_ttl(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs('data')
    now = time.time()
    json.dump({'a': now - 2 * 86400, 'b': now - 2 * 86400, 'c': now - 2 * 86400, 'd': now - 20 * 86400},
              open('data/dice_failed_ids.json', 'w'))
    json.dump({'a': 'incomplete', 'b': 'no_apply_button', 'c': 'login_redirect', 'd': 'no_apply_button'},
              open('data/dice_failed_reasons.json', 'w'))
    monkeypatch.setattr(d, 'FAILED_FILE', 'data/dice_failed_ids.json')
    monkeypatch.setattr(d, 'REASONS_FILE', 'data/dice_failed_reasons.json')
    blocked = d._load_failed_fresh()
    assert blocked == {'b'}   # incomplete(1d) expired, login_redirect(0) never blocks, 20d no_apply_button expired
