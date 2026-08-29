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


class TestWeeklyProjectedValueRows:
    def test_computes_dot_product_against_scoring_settings(self):
        players = {"a": make_player("WR")}
        projections = {"a": {"rec": 5.0, "rec_yd": 50.0, "rec_td": 1.0}}
        scoring_settings = {"rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0}

        rows = dc.weekly_projected_value_rows(["a"], players, projections, scoring_settings)

        assert rows == [{"player_id": "a", "pos": "WR", "adj_value": 16.0}]  # 5*1 + 50*0.1 + 1*6

    def test_missing_projection_entry_yields_none_adj_value(self):
        players = {"a": make_player("WR")}

        rows = dc.weekly_projected_value_rows(["a"], players, {}, {"rec": 1.0})

        assert rows[0]["adj_value"] is None

    def test_non_fantasy_position_is_excluded(self):
        players = {"a": {"position": "DEF", "team": "AAA", "full_name": "Defense"}}
        projections = {"a": {"def_td": 1.0}}

        rows = dc.weekly_projected_value_rows(["a"], players, projections, {"def_td": 6.0})

        assert rows == []

    def test_te_missing_bonus_rec_te_key_falls_back_to_deriving_it_from_rec(self):
        """Sleeper usually emits bonus_rec_te directly (VA-7); this covers the rare
        projection that omits it, where the code must still derive it from rec."""
        players = {"a": make_player("TE")}
        projections = {"a": {"rec": 5.0}}
        scoring_settings = {"rec": 1.0, "bonus_rec_te": 0.5}

        rows = dc.weekly_projected_value_rows(["a"], players, projections, scoring_settings)

        assert rows == [{"player_id": "a", "pos": "TE", "adj_value": 7.5}]  # 5*1 + 5*0.5

    def test_te_bonus_rec_te_already_in_projection_is_not_double_counted(self):
        """Live Sleeper projections do emit bonus_rec_te scoped to TEs (VA-7) - the
        generic dot product already prices it in once, so the fallback must not add
        it a second time."""
        players = {"a": make_player("TE")}
        projections = {"a": {"rec": 5.0, "bonus_rec_te": 5.0}}
        scoring_settings = {"rec": 1.0, "bonus_rec_te": 0.5}

        rows = dc.weekly_projected_value_rows(["a"], players, projections, scoring_settings)

        assert rows == [{"player_id": "a", "pos": "TE", "adj_value": 7.5}]  # 5*1 + 5*0.5, once

    def test_non_te_does_not_get_bonus_rec_te_applied(self):
        players = {"a": make_player("WR")}
        projections = {"a": {"rec": 5.0}}
        scoring_settings = {"rec": 1.0, "bonus_rec_te": 0.5}

        rows = dc.weekly_projected_value_rows(["a"], players, projections, scoring_settings)

        assert rows == [{"player_id": "a", "pos": "WR", "adj_value": 5.0}]

    def test_non_numeric_stat_value_is_skipped_not_crashed_on(self):
        players = {"a": make_player("WR")}
        projections = {"a": {"rec": 5.0, "some_undocumented_field": None}}
        scoring_settings = {"rec": 1.0, "some_undocumented_field": 2.0}

        rows = dc.weekly_projected_value_rows(["a"], players, projections, scoring_settings)

        assert rows == [{"player_id": "a", "pos": "WR", "adj_value": 5.0}]


class TestWeeklyLineupBreakdown:
    def test_disagrees_with_dynasty_value_ranking_when_projections_differ(self):
        # wr1 is the better dynasty asset; wr2 is projected to score far more
        # this week - the two rankings should pick different starters,
        # proving weekly_lineup_breakdown() actually plumbs projected points
        # through assign_starters(), not a copy of the dynasty-value ranking.
        players = {"wr1": make_player("WR"), "wr2": make_player("WR")}
        roster = {"players": list(players.keys())}
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("wr1", 500, position="WR"), fc_entry("wr2", 100, position="WR")]
        )
        projections = {"wr1": {"rec_yd": 10.0}, "wr2": {"rec_yd": 200.0}}
        league = {"roster_positions": ["WR"], "scoring_settings": {"rec_yd": 0.1}}

        value_starters, *_ = dc.lineup_breakdown(roster, players, fc_by_id, league)
        weekly_starters, *_ = dc.weekly_lineup_breakdown(roster, players, projections, league)

        assert list(value_starters["name"]) == [players["wr1"]["full_name"]]
        assert list(weekly_starters["name"]) == [players["wr2"]["full_name"]]

    def test_taxi_and_reserve_players_are_split_from_bench(self):
        players = {
            "starter": make_player("QB"),
            "bench1": make_player("RB"),
            "taxi1": make_player("WR"),
            "ir1": make_player("TE"),
        }
        roster = {"players": list(players.keys()), "taxi": ["taxi1"], "reserve": ["ir1"]}
        projections = {pid: {"pass_yd": 1.0} for pid in players}
        league = {"roster_positions": ["QB", "BN"], "scoring_settings": {"pass_yd": 1.0}}

        _starters, bench, taxi, ir = dc.weekly_lineup_breakdown(roster, players, projections, league)

        assert list(bench["name"]) == [players["bench1"]["full_name"]]
        assert list(taxi["name"]) == [players["taxi1"]["full_name"]]
        assert list(ir["name"]) == [players["ir1"]["full_name"]]

    def test_empty_projections_degrades_to_all_none_values_not_a_crash(self):
        players = {"wr1": make_player("WR")}
        roster = {"players": list(players.keys())}
        league = {"roster_positions": ["WR"], "scoring_settings": {"rec_yd": 0.1}}

        starters, *_ = dc.weekly_lineup_breakdown(roster, players, {}, league)

        assert list(starters["adj_value"]) == [None]


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
