"""Tests for dynasty_core.league_summary."""

from __future__ import annotations

import pandas as pd
import pytest

import dynasty_core as dc
from tests.dynasty_core.helpers import fc_entry, make_player


class TestLeagueTeamSummaries:
    """One row per team - total value, biggest need, capacity, power/timeline read."""

    def test_one_row_per_team_with_expected_columns(self):
        league = {
            "roster_positions": ["QB", "RB", "WR", "BN"],
            "settings": {"taxi_slots": 1, "reserve_slots": 0},
        }
        players = {
            "qb1": make_player("QB", full_name="QB One"),
            "wr1": make_player("WR", full_name="WR One"),
            "rb1": make_player("RB", full_name="RB One"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("qb1", 100), fc_entry("wr1", 200), fc_entry("rb1", 50)]
        )
        rosters_by_id = {
            1: {"roster_id": 1, "players": ["qb1", "wr1"], "taxi": [], "reserve": []},
            2: {"roster_id": 2, "players": ["rb1"], "taxi": [], "reserve": []},
        }
        team_names = {1: "Team One", 2: "Team Two"}
        # Team 2's lone RB falls well short of a 100-value replacement level;
        # QB/WR/TE have a 0 replacement level, so being unrostered there
        # scores as neutral (vor=0), not worse than the RB gap - RB should
        # come out as team 2's uniquely biggest need.
        replacement_level = {"QB": 0.0, "RB": 100.0, "WR": 0.0, "TE": 0.0}
        power_timeline = pd.DataFrame(
            {"phase": ["contending", "rebuilding"], "rank": [1, 2], "win_pct": [0.6, 0.4], "games_played": [5, 5]},
            index=pd.Index([1, 2], name="roster_id"),
        )

        summary = dc.league_team_summaries(
            rosters_by_id, players, fc_by_id, {}, league, replacement_level, team_names, power_timeline
        )

        assert list(summary.index) == [1, 2]
        assert summary.loc[1, "team"] == "Team One"
        assert summary.loc[1, "total_value"] == pytest.approx(300.0)  # 100 + 200
        assert summary.loc[2, "total_value"] == pytest.approx(50.0)
        assert summary.loc[2, "biggest_need"] == "RB"
        assert summary.loc[1, "active_open"] == 2  # 4 slots - 2 rostered
        assert summary.loc[2, "phase"] == "rebuilding"
        assert summary.loc[2, "rank"] == 2

    def test_empty_roster_gets_zero_value_and_full_capacity(self):
        league = {"roster_positions": ["QB", "BN"], "settings": {"taxi_slots": 0, "reserve_slots": 0}}
        rosters_by_id = {1: {"roster_id": 1, "players": [], "taxi": [], "reserve": []}}
        power_timeline = pd.DataFrame(
            {"phase": ["rebuilding"], "rank": [1], "win_pct": [0.5], "games_played": [0]},
            index=pd.Index([1], name="roster_id"),
        )

        summary = dc.league_team_summaries(
            rosters_by_id, {}, {}, {}, league, {"QB": 0.0, "RB": 0.0, "WR": 0.0, "TE": 0.0}, {}, power_timeline
        )

        assert summary.loc[1, "total_value"] == 0.0
        assert summary.loc[1, "active_open"] == 2
        assert summary.loc[1, "team"] == "Roster 1"  # falls back when team_names has no entry
