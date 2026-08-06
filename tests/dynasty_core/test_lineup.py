"""Tests for dynasty_core.lineup."""

from __future__ import annotations

import dynasty_core as dc
from tests.dynasty_core.helpers import fc_entry, make_player


class TestRosterCapacity:
    """IR/reserve players must not count against active-roster capacity, same as taxi."""

    def test_reserve_players_are_excluded_from_active_filled(self):
        league = {
            "roster_positions": ["QB", "RB", "WR", "BN", "BN"],
            "settings": {"taxi_slots": 1, "reserve_slots": 2},
        }
        roster = {"players": ["p1", "p2", "p3", "p4", "p5"], "taxi": ["p5"], "reserve": ["p3", "p4"]}

        cap = dc.roster_capacity(roster, league)

        # 5 rostered - 1 taxi - 2 reserve = 2 genuinely on the active roster.
        assert cap["active_filled"] == 2
        assert cap["active_open"] == 3
        assert cap["reserve_filled"] == 2
        assert cap["reserve_open"] == 0


class TestLineupBreakdown:
    """Taxi and IR/reserve players should be split out, not lumped into bench."""

    def test_taxi_and_reserve_players_are_split_from_bench(self):
        players = {
            "starter": make_player("QB"),
            "bench1": make_player("RB"),
            "taxi1": make_player("WR"),
            "ir1": make_player("TE"),
        }
        roster = {"players": list(players.keys()), "taxi": ["taxi1"], "reserve": ["ir1"]}
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry(pid, 100, position=info["position"]) for pid, info in players.items()]
        )
        league = {"roster_positions": ["QB", "BN"]}

        _starters, bench, taxi, ir = dc.lineup_breakdown(roster, players, fc_by_id, league)

        assert list(bench["name"]) == [players["bench1"]["full_name"]]
        assert list(taxi["name"]) == [players["taxi1"]["full_name"]]
        assert list(ir["name"]) == [players["ir1"]["full_name"]]


class TestAssignStarters:
    """assign_starters: most-restrictive-slot-first, provably optimal for nested eligibility."""

    def test_dedicated_slots_get_the_best_player_at_that_position(self):
        players = {"qb1": make_player("QB"), "rb1": make_player("RB"), "wr1": make_player("WR")}
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("qb1", 100), fc_entry("rb1", 200), fc_entry("wr1", 50)])
        rows = dc.player_value_rows(list(players.keys()), players, fc_by_id)

        assignments = dict(dc.assign_starters(rows, ["QB", "RB", "WR"]))

        assert assignments == {"QB": "qb1", "RB": "rb1", "WR": "wr1"}

    def test_super_flex_takes_best_remaining_value_regardless_of_position(self):
        # A second QB, if more valuable than the best remaining RB, should
        # win SUPER_FLEX over that RB - SUPER_FLEX pulls the single best
        # remaining player from ANY eligible position, not "whatever's left
        # of the other positions first."
        players = {"qb1": make_player("QB"), "qb2": make_player("QB"), "rb1": make_player("RB")}
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("qb1", 300), fc_entry("qb2", 150), fc_entry("rb1", 100)])
        rows = dc.player_value_rows(list(players.keys()), players, fc_by_id)

        assignments = dict(dc.assign_starters(rows, ["QB", "SUPER_FLEX"]))

        assert assignments["QB"] == "qb1"
        assert assignments["SUPER_FLEX"] == "qb2"

    def test_slot_is_empty_when_no_eligible_player_remains(self):
        players = {"wr1": make_player("WR")}
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("wr1", 100)])
        rows = dc.player_value_rows(list(players.keys()), players, fc_by_id)

        assignments = dict(dc.assign_starters(rows, ["QB", "WR"]))

        assert assignments["QB"] is None
        assert assignments["WR"] == "wr1"
