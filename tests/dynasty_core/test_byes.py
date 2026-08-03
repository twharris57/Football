"""Tests for dynasty_core.byes."""

from __future__ import annotations

import pytest

import dynasty_core as dc
from tests.dynasty_core.helpers import fc_entry, make_player


class TestRosterByeConflicts:
    """One row per week with an active-roster player out, showing who fills in and the value delta."""

    def test_bench_filler_and_delta_shown_for_the_bye_week_only(self):
        roster = {"players": ["starter_qb", "bench_qb"], "taxi": [], "reserve": []}
        players = {
            "starter_qb": make_player("QB", team="AAA", full_name="Starter QB"),
            "bench_qb": make_player("QB", team="BBB", full_name="Bench QB"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("starter_qb", 100), fc_entry("bench_qb", 50)])
        byes = {"AAA": 3}
        league = {"roster_positions": ["QB"]}

        conflicts = dc.roster_bye_conflicts(roster, players, fc_by_id, byes, league)

        assert list(conflicts["week"]) == [3]
        row = conflicts.iloc[0]
        assert "Starter QB" in row["starters_out"]
        assert "Bench QB" in row["fillers"]
        assert row["lineup_delta"] == pytest.approx(-50.0)

    def test_taxi_and_reserve_players_are_not_eligible_fillers(self):
        # A high-value taxi player must not be "assigned" to cover a bye -
        # Sleeper doesn't allow starting a taxi/IR player.
        roster = {"players": ["starter_qb", "taxi_qb"], "taxi": ["taxi_qb"], "reserve": []}
        players = {
            "starter_qb": make_player("QB", team="AAA", full_name="Starter QB"),
            "taxi_qb": make_player("QB", team="BBB", full_name="Taxi QB"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("starter_qb", 100), fc_entry("taxi_qb", 500)])
        byes = {"AAA": 3}
        league = {"roster_positions": ["QB"]}

        conflicts = dc.roster_bye_conflicts(roster, players, fc_by_id, byes, league)

        assert list(conflicts["week"]) == [3]
        row = conflicts.iloc[0]
        assert row["fillers"] == "(none - bench absorbs it)"
        assert row["lineup_delta"] == pytest.approx(-100.0)

    def test_bench_only_bye_shows_no_starters_out_and_zero_delta(self):
        # A bench player's bye shouldn't show up as a "starter out" - it
        # doesn't cost any lineup value, so it belongs in bench_out, not
        # the at-a-glance starters_out/fillers pair.
        roster = {"players": ["starter_qb", "bench_wr"], "taxi": [], "reserve": []}
        players = {
            "starter_qb": make_player("QB", team="AAA", full_name="Starter QB"),
            "bench_wr": make_player("WR", team="BBB", full_name="Bench WR"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("starter_qb", 100), fc_entry("bench_wr", 20)])
        byes = {"BBB": 4}
        league = {"roster_positions": ["QB"]}

        conflicts = dc.roster_bye_conflicts(roster, players, fc_by_id, byes, league)

        assert list(conflicts["week"]) == [4]
        row = conflicts.iloc[0]
        assert row["starters_out"] == "(none - only bench players out)"
        assert "Bench WR" in row["bench_out"]
        assert row["lineup_delta"] == pytest.approx(0.0)


class TestRosterWeeklyGaps:
    """A dedicated slot with no available player that week should be flagged, and only that week."""

    def test_flags_only_the_bye_week_for_a_single_covered_position(self):
        players = {"qb1": make_player("QB", team="AAA")}
        roster = {"players": ["qb1"]}
        byes = {"AAA": 7}
        league = {"roster_positions": ["QB"]}

        gaps = dc.roster_weekly_gaps(roster, players, byes, league)

        assert gaps.loc[gaps["week"] == 7, "gap"].iloc[0] == "QB"
        assert gaps.loc[gaps["week"] == 1, "gap"].iloc[0] == ""
