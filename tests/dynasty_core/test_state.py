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


def _change(player_id: str, kind: str = "team", old=None, new="KC") -> dict:
    return {"player_id": player_id, "kind": kind, "old": old, "new": new}


def _ranked_row(player_id: str, marginal_value: float, drop: dict | None = None) -> dict:
    return {"player_id": player_id, "marginal_value": marginal_value, "drop": drop}


PLAYERS = {
    "p1": {"full_name": "New Guy", "position": "WR", "team": "KC"},
    "p2": {"full_name": "Other Guy", "position": "RB", "team": "SF"},
}


class TestBuildPickupAlerts:
    """A raw marginal_value must be rounded before the >0 "worth surfacing"
    filter runs, matching free_agent_board()'s own round-then-filter order -
    otherwise a real-but-tiny value can pass the filter and still render as
    the self-contradicting "would add +0.0 to your lineup" once summary.py
    formats it to one decimal (VA-6, valuation_principles.md)."""

    def test_a_raw_value_that_rounds_to_zero_is_excluded(self):
        changes = [_change("p1")]
        ranked = [_ranked_row("p1", 0.03)]

        assert dc.build_pickup_alerts(changes, ranked, PLAYERS) == []

    def test_a_raw_value_that_rounds_to_a_real_positive_is_included(self):
        changes = [_change("p1")]
        ranked = [_ranked_row("p1", 0.06)]

        alerts = dc.build_pickup_alerts(changes, ranked, PLAYERS)

        assert len(alerts) == 1
        assert alerts[0]["marginal_value"] == 0.1

    def test_a_negative_or_zero_value_is_excluded(self):
        changes = [_change("p1"), _change("p2")]
        ranked = [_ranked_row("p1", 0.0), _ranked_row("p2", -3.0)]

        assert dc.build_pickup_alerts(changes, ranked, PLAYERS) == []

    def test_carries_drop_name_and_is_starter_through(self):
        changes = [_change("p1")]
        ranked = [_ranked_row("p1", 8.0, drop={"player_id": "p9", "name": "Starter WR", "is_starter": True})]

        alerts = dc.build_pickup_alerts(changes, ranked, PLAYERS)

        assert alerts[0]["drop_name"] == "Starter WR"
        assert alerts[0]["drop_is_starter"] is True

    def test_sorts_best_marginal_value_first(self):
        changes = [_change("p1"), _change("p2")]
        ranked = [_ranked_row("p1", 2.0), _ranked_row("p2", 9.0)]

        alerts = dc.build_pickup_alerts(changes, ranked, PLAYERS)

        assert [a["player_id"] for a in alerts] == ["p2", "p1"]
