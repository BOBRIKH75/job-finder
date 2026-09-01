#!/usr/bin/env python3
"""Self-learning selector store for Indeed apply buttons.

Problem (verified live 2026-09-01): Indeed renders its apply button
inconsistently and with different text/attributes ("Apply with Indeed",
"Apply now", "Easy Apply", data-testid variants, in iframes, etc.).
A single hardcoded selector misses most jobs.

Solution: a growing knowledge base.
  - KNOWN selectors are tried every run, ordered by past success (wins).
  - When NO known selector matches, we scrape the page for ANY apply-like
    element and SAVE its selector as a new candidate — so the NEXT run
    tries it too. Over time we cover every variation Indeed uses.
  - When a selector successfully reaches the apply form, we bump its win
    count so it floats to the top.

Store file: agent/data/indeed_selectors.json
Schema:
{
  "selectors": [
    {"selector": "button:has-text(\"Apply with Indeed\")", "wins": 12, "seen": 40,
     "source": "seed", "last_win": "2026-09-01T..."},
    ...
  ],
  "runs": 5,
  "updated": "..."
}
"""
import json
import os
from datetime import datetime

STORE_PATH = os.path.join(os.path.dirname(__file__), 'agent', 'data', 'indeed_selectors.json')

# Seed selectors — the variations we already know Indeed uses.
SEED_SELECTORS = [
    'button:has-text("Apply with Indeed")',
    'a:has-text("Apply with Indeed")',
    '[data-testid="indeedApplyButton"]',
    'button:has-text("Apply now")',
    'button:has-text("Easy Apply")',
    '#indeedApplyButton',
    'button[id^="indeedApply"]',
    'div.indeed-apply-button',
    'span:has-text("Apply with Indeed")',
    'button:has-text("Apply")',
]


def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')


def load_store() -> dict:
    """Load the selector store, seeding it on first use."""
    if os.path.exists(STORE_PATH):
        try:
            store = json.loads(open(STORE_PATH).read())
            if store.get('selectors'):
                # Ensure any brand-new seeds are merged in (so upgrades add coverage).
                known = {s['selector'] for s in store['selectors']}
                for sel in SEED_SELECTORS:
                    if sel not in known:
                        store['selectors'].append(
                            {'selector': sel, 'wins': 0, 'seen': 0,
                             'source': 'seed', 'last_win': None})
                return store
        except Exception:
            pass
    # First run — seed it.
    return {
        'selectors': [
            {'selector': sel, 'wins': 0, 'seen': 0, 'source': 'seed', 'last_win': None}
            for sel in SEED_SELECTORS
        ],
        'runs': 0,
        'updated': _now(),
    }


def save_store(store: dict) -> None:
    store['updated'] = _now()
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    with open(STORE_PATH, 'w') as f:
        json.dump(store, f, indent=2)


def ranked_selectors(store: dict) -> list:
    """Return selector strings ordered best-first (most wins, then most seen)."""
    ordered = sorted(
        store['selectors'],
        key=lambda s: (s.get('wins', 0), s.get('seen', 0)),
        reverse=True,
    )
    return [s['selector'] for s in ordered]


def record_win(store: dict, selector: str) -> None:
    """A selector reached the apply form — bump it to the top over time."""
    for s in store['selectors']:
        if s['selector'] == selector:
            s['wins'] = s.get('wins', 0) + 1
            s['seen'] = s.get('seen', 0) + 1
            s['last_win'] = _now()
            return
    store['selectors'].append(
        {'selector': selector, 'wins': 1, 'seen': 1,
         'source': 'learned', 'last_win': _now()})


def record_seen(store: dict, selector: str) -> None:
    """A selector matched an element (present) even if apply didn't complete."""
    for s in store['selectors']:
        if s['selector'] == selector:
            s['seen'] = s.get('seen', 0) + 1
            return


def learn_from_page(store: dict, page) -> list:
    """When no known selector worked, scrape the live page for ANY apply-like
    element and add its selector as a new candidate for next time.

    Returns the list of newly learned selector strings (also tried this run).
    Runs entirely in the browser via JS so it works inside the real DOM.
    """
    learned = []
    try:
        candidates = page.evaluate(
            """
            () => {
                const out = [];
                const els = document.querySelectorAll(
                    'button, a, [role="button"], input[type="submit"], div[class*="apply" i], span[class*="apply" i]'
                );
                for (const el of els) {
                    const txt = (el.textContent || el.value || '').trim().toLowerCase();
                    const id = el.id || '';
                    const testid = el.getAttribute('data-testid') || '';
                    const cls = (el.className || '').toString();
                    const looksApply =
                        txt.includes('apply') ||
                        id.toLowerCase().includes('apply') ||
                        testid.toLowerCase().includes('apply') ||
                        cls.toLowerCase().includes('apply');
                    if (!looksApply) continue;
                    // Build the most specific stable selector we can.
                    if (id) {
                        out.push('#' + CSS.escape(id));
                    } else if (testid) {
                        out.push('[data-testid="' + testid + '"]');
                    } else if (txt && txt.length < 40) {
                        // Preserve original case for :has-text by reading raw text
                        const raw = (el.textContent || '').trim();
                        out.push('TEXT::' + el.tagName.toLowerCase() + '::' + raw);
                    }
                }
                return [...new Set(out)];
            }
            """
        )
        for cand in candidates:
            if cand.startswith('TEXT::'):
                _, tag, raw = cand.split('::', 2)
                # Escape embedded quotes for the :has-text() argument.
                safe = raw.replace('"', '\\"')
                selector = f'{tag}:has-text("{safe}")'
            else:
                selector = cand
            known = {s['selector'] for s in store['selectors']}
            if selector not in known:
                store['selectors'].append(
                    {'selector': selector, 'wins': 0, 'seen': 1,
                     'source': 'learned', 'last_win': None})
                learned.append(selector)
    except Exception:
        pass
    return learned


def bump_runs(store: dict) -> None:
    store['runs'] = store.get('runs', 0) + 1
