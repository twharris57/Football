"""Regression test for load_state's cache-busting key (dynasty/streamlit_app.py).

Streamlit's `st.cache_data` silently excludes any argument whose name starts
with "_" from the cache key entirely - a real, documented convention for
genuinely unhashable arguments (e.g. DB connections), but `load_state`'s
cache-busting token is a plain `float`, which was always hashable and never
needed it. A prior version of this parameter was named `_token`: the Refresh
button, the session_state write, and the spinner all "worked," but the
token's value never actually affected caching, so a plain Refresh silently
kept returning whatever was cached under the first-ever call in the
process's lifetime (found live on the Synology deployment, 2026-08-16 - see
PROJECT_PLAN.md). Two earlier fixes changed the token's *value* without
renaming it, so neither actually fixed the bug.

Drives the real app via Streamlit's AppTest, monkeypatching
dynasty_core.gather_state to a call counter instead of hitting Sleeper/
FantasyCalc (testing.md: mock only external services this project doesn't
control). The fake state only needs the fields streamlit_app.py reads before
the tabs render (current_pick_no <= 0 picks means "Draft complete," skipping
the on-the-clock lookup) - AppTest captures any later tab-rendering
exception in `at.exception` without failing `.run()`, so an intentionally
incomplete fake state doesn't need to satisfy every tab.
"""

from __future__ import annotations

import dynasty_core
from streamlit.testing.v1 import AppTest

_FAKE_STATE = {
    "league": {"name": "Test League", "season": "2026", "status": "drafting"},
    "data_warnings": [],
    "ownership": [],
    "current_pick_no": 1,
    "picks_until_turn": None,
    "team_names": {},
}


def test_refresh_click_busts_the_load_state_cache(monkeypatch):
    calls = {"n": 0}

    def fake_gather_state(league_id, username, force_full_refresh, force_scoring_refresh=False):
        calls["n"] += 1
        return dict(_FAKE_STATE)

    monkeypatch.setattr(dynasty_core, "gather_state", fake_gather_state)

    at = AppTest.from_file("dynasty/streamlit_app.py")
    at.run()
    assert calls["n"] == 1

    at.sidebar.button[0].click().run()  # "Refresh"
    assert calls["n"] == 2, "a plain Refresh click must bust load_state's cache and re-fetch"

    at.sidebar.button[0].click().run()
    assert calls["n"] == 3, "every Refresh click must be a real re-fetch, not just the first one"
