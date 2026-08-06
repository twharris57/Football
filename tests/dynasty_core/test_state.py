"""Tests for dynasty_core.state.

`TestGatherStateConnectivityErrors` monkeypatches sleeper_api/fantasycalc_api
directly, which testing.md's "mock only external services you do not
control" explicitly allows.
"""

from __future__ import annotations

import pytest
import requests

import dynasty_core as dc


class TestGatherStateConnectivityErrors:
    """A connectivity failure should name which upstream service failed,
    not a generic "Sleeper/FantasyCalc" either-or - draft day means
    everyone hits both unauthenticated public APIs at once, so knowing
    which one is actually down matters for deciding whether to retry."""

    def test_sleeper_failure_is_named(self, monkeypatch):
        def raise_it(*args, **kwargs):
            raise requests.ConnectionError("boom")

        monkeypatch.setattr(dc.sleeper, "get_league", raise_it)

        with pytest.raises(requests.RequestException, match="Couldn't reach Sleeper"):
            dc.gather_state("league1", "user1", False)

    def test_fantasycalc_failure_is_named(self, monkeypatch):
        league = {
            "draft_id": "d1",
            "roster_positions": ["QB", "RB", "WR", "TE", "BN"],
            "settings": {"num_teams": 12},
            "scoring_settings": {"rec": 1.0},
        }
        monkeypatch.setattr(dc.sleeper, "get_league", lambda league_id: league)
        monkeypatch.setattr(dc.sleeper, "get_rosters", lambda league_id: [])
        monkeypatch.setattr(dc.sleeper, "get_users", lambda league_id: [])
        monkeypatch.setattr(dc.sleeper, "get_draft", lambda draft_id: {})
        monkeypatch.setattr(dc.sleeper, "get_draft_picks", lambda draft_id: [])
        monkeypatch.setattr(dc.sleeper, "get_traded_picks", lambda league_id: [])
        monkeypatch.setattr(dc.sleeper, "get_players", lambda force_refresh=False: {})

        def raise_it(**kwargs):
            raise requests.ConnectionError("boom")

        monkeypatch.setattr(dc.fantasycalc, "get_dynasty_values", raise_it)

        with pytest.raises(requests.RequestException, match="Couldn't reach FantasyCalc"):
            dc.gather_state("league1", "user1", False)
