"""Tests for dynasty_core.team_analysis."""

from __future__ import annotations

import pytest

import dynasty_core as dc
from tests.dynasty_core.helpers import fc_entry, make_player


class TestTeamRosterAnalysis:
    """team_roster_analysis should bundle every per-roster view for ANY roster,
    not just the user's own - the basis for the Roster tab's team selector."""

    def test_bundles_every_view_for_an_arbitrary_roster(self):
        league = {
            "roster_positions": ["QB", "WR", "BN"],
            "settings": {"taxi_slots": 1, "reserve_slots": 1},
            "scoring_settings": {"pass_yd": 0.04, "rec_yd": 0.1},
        }
        players = {
            "qb1": make_player("QB", team="AAA", full_name="QB One"),
            "wr1": make_player("WR", team="AAA", full_name="WR One"),
        }
        # position deliberately omitted from fc_entry - passing "QB" would
        # trigger the real POSITION_VALUE_MULTIPLIER fallback (1.175x) and
        # break this test's hand-computed vor math below.
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("qb1", 100), fc_entry("wr1", 200)])
        roster = {"players": ["qb1", "wr1"], "taxi": [], "reserve": []}
        replacement_level = {"QB": 50.0, "RB": 0.0, "WR": 50.0, "TE": 0.0}

        analysis = dc.team_roster_analysis(roster, players, fc_by_id, {}, league, {}, replacement_level, {})

        assert set(analysis.keys()) == {
            "roster_needs",
            "need_positions",
            "roster_capacity",
            "roster_value",
            "sellable_players",
            "free_agent_board",
            "roster_bye_conflicts",
            "roster_weekly_gaps",
            "roster_handcuffs",
            "lineup_starters",
            "lineup_bench",
            "lineup_taxi",
            "lineup_ir",
            "weekly_lineup_starters",
            "weekly_lineup_bench",
            "weekly_lineup_taxi",
            "weekly_lineup_ir",
        }
        assert analysis["roster_capacity"]["active_filled"] == 2
        assert set(analysis["lineup_starters"]["name"]) == {"QB One", "WR One"}
        # positional_strength_summary's vor/weak columns get joined onto
        # roster_needs_summary's young-core need columns, not left as a
        # separate table - two different questions about the same position.
        needs = analysis["roster_needs"]
        assert needs.loc["QB", "vor"] == pytest.approx(50.0)  # 100 adj_value - 50 replacement
        assert not needs.loc["QB", "weak"]
        assert needs.loc["WR", "vor"] == pytest.approx(150.0)  # 200 adj_value - 50 replacement
        assert not needs.loc["WR", "weak"]
