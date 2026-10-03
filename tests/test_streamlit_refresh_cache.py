"""Refresh must actually re-fetch.

`st.cache_data` ignores arguments whose names start with "_", so a `_token` parameter
would silently make Refresh a no-op. Drives the real app with AppTest and a counting
`gather_state` stub. The fake state only covers what renders before the tabs; tab
errors land in `at.exception` without failing `.run()`.
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
