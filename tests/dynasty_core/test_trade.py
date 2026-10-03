"""Tests for dynasty_core.trade."""

from __future__ import annotations

import math

import pandas as pd
import pytest

import dynasty_core as dc
from dynasty_core import trade as trade_module
from tests.dynasty_core.helpers import EMPTY_PICKS, fc_entry, make_player


class TestSellablePlayers:
    """Sellable = surplus-position bench depth; never starters or rookies, and never a weekly-gap risk."""

    def test_flags_depth_beyond_starters_excludes_starter_and_rookie(self):
        league = {"roster_positions": ["WR", "BN", "BN"]}
        players = {
            "wr1": make_player("WR", full_name="Starter WR"),
            "wr2": make_player("WR", full_name="Depth WR"),
            "wr3": make_player("WR", full_name="Rookie WR"),
        }
        players["wr1"]["years_exp"] = 5
        players["wr2"]["years_exp"] = 3
        players["wr3"]["years_exp"] = 0
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("wr1", 500, position="WR"), fc_entry("wr2", 300, position="WR"), fc_entry("wr3", 200, position="WR")]
        )
        roster = {"players": ["wr1", "wr2", "wr3"]}
        replacement_level = {"WR": 50.0, "QB": 0.0, "RB": 0.0, "TE": 0.0}

        sellable = dc.sellable_players(roster, players, fc_by_id, replacement_level, league, byes={})

        # wr1 starts, wr3 is a rookie; only wr2 is sellable.
        assert list(sellable["name"]) == ["Depth WR"]
        assert list(sellable["player_id"]) == ["wr2"]
        assert sellable.iloc[0]["position_vor"] == pytest.approx(450.0)  # 500 - 50

    def test_excludes_a_depth_candidate_that_would_open_a_weekly_gap(self):
        league = {"roster_positions": ["WR", "BN"]}
        players = {
            "wr1": make_player("WR", team="AAA", full_name="Starter WR"),
            "wr2": make_player("WR", team="BBB", full_name="Depth WR"),
        }
        players["wr1"]["years_exp"] = 5
        players["wr2"]["years_exp"] = 3
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("wr1", 500, position="WR"), fc_entry("wr2", 300, position="WR")])
        roster = {"players": ["wr1", "wr2"]}
        replacement_level = {"WR": 50.0, "QB": 0.0, "RB": 0.0, "TE": 0.0}
        byes = {"AAA": 5}  # dropping wr2 would leave only wr1, who's on bye week 5

        sellable = dc.sellable_players(roster, players, fc_by_id, replacement_level, league, byes)

        assert sellable.empty

    def test_no_candidates_from_a_position_that_doesnt_clear_replacement(self):
        league = {"roster_positions": ["RB", "BN", "BN"]}
        players = {
            "rb1": make_player("RB", full_name="RB One"),
            "rb2": make_player("RB", full_name="RB Two"),
        }
        players["rb1"]["years_exp"] = 4
        players["rb2"]["years_exp"] = 3
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("rb1", 50, position="RB"), fc_entry("rb2", 20, position="RB")])
        roster = {"players": ["rb1", "rb2"]}
        replacement_level = {"RB": 200.0, "QB": 0.0, "WR": 0.0, "TE": 0.0}

        sellable = dc.sellable_players(roster, players, fc_by_id, replacement_level, league, byes={})

        assert sellable.empty

    def test_reserves_flex_range_from_depth_when_league_has_a_flex_slot(self):
        # 2 dedicated RB slots + 1 FLEX - the real, weekly-startable RB
        # range is 3 deep, not 2. Only the 4th-best RB is genuine surplus.
        league = {"roster_positions": ["RB", "RB", "FLEX", "BN", "BN"]}
        players = {f"rb{i}": make_player("RB", full_name=f"RB {i}") for i in range(1, 5)}
        for p in players.values():
            p["years_exp"] = 4
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("rb1", 500, position="RB"), fc_entry("rb2", 400, position="RB"),
             fc_entry("rb3", 300, position="RB"), fc_entry("rb4", 100, position="RB")]
        )
        roster = {"players": ["rb1", "rb2", "rb3", "rb4"]}
        replacement_level = {"RB": 50.0, "QB": 0.0, "WR": 0.0, "TE": 0.0}

        sellable = dc.sellable_players(roster, players, fc_by_id, replacement_level, league, byes={})

        # rb3 is a real FLEX-range starter (protected) - only rb4 is
        # genuine depth beyond the dedicated-plus-FLEX range.
        assert list(sellable["name"]) == ["RB 4"]


class TestEvaluateTrade:
    """Independent lineup and asset reads per side; the other side is the same call swapped."""

    def test_clearly_better_incoming_player_raises_lineup_value(self):
        league = {"roster_positions": ["WR", "BN"]}
        roster = {"players": ["old_wr"], "taxi": [], "reserve": []}
        players = {
            "old_wr": make_player("WR", full_name="Old WR"),
            "new_wr": make_player("WR", full_name="New WR"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("old_wr", 100), fc_entry("new_wr", 900)])

        result = dc.evaluate_trade(roster, ["old_wr"], ["new_wr"], players, fc_by_id, {}, league)

        assert result["lineup_delta"] > 0
        assert result["asset_value_delta"] == pytest.approx(900 - 100)

    def test_multi_for_multi_trade_reflects_net_roster_size_change(self):
        # 2 outgoing for 1 incoming - roster shrinks by 1, well under capacity.
        league = {"roster_positions": ["WR", "BN"]}
        roster = {"players": ["a", "b"], "taxi": [], "reserve": []}
        players = {
            "a": make_player("WR", full_name="A"),
            "b": make_player("WR", full_name="B"),
            "c": make_player("WR", full_name="C"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("a", 100), fc_entry("b", 100), fc_entry("c", 900)])

        result = dc.evaluate_trade(roster, ["a", "b"], ["c"], players, fc_by_id, {}, league)

        assert result["roster_size_after"] == 1
        assert not result["over_capacity"]

    def test_flags_over_capacity_when_incoming_outnumbers_outgoing(self):
        # League capacity (active-only, taxi_eligible=False) is 2. Roster
        # starts at 2 (full); 1 outgoing for 2 incoming pushes to 3 - over.
        league = {"roster_positions": ["WR", "BN"]}
        roster = {"players": ["a", "b"], "taxi": [], "reserve": []}
        players = {
            "a": make_player("WR", full_name="A"),
            "b": make_player("WR", full_name="B"),
            "c": make_player("WR", full_name="C"),
            "d": make_player("WR", full_name="D"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("a", 100), fc_entry("b", 100), fc_entry("c", 200), fc_entry("d", 200)]
        )

        result = dc.evaluate_trade(roster, ["a"], ["c", "d"], players, fc_by_id, {}, league)

        assert result["roster_size_after"] == 3
        assert result["capacity"] == 2
        assert result["over_capacity"]

    def test_recommends_a_drop_when_over_capacity_and_never_the_incoming_players(self):
        # Roster a, b (100 each) gets c, d (200 each) for a: one over. b is the only
        # eligible drop and wasn't starting, so both lineup deltas match.
        league = {"roster_positions": ["WR", "BN"]}
        roster = {"players": ["a", "b"], "taxi": [], "reserve": []}
        players = {
            "a": make_player("WR", full_name="A"),
            "b": make_player("WR", full_name="B"),
            "c": make_player("WR", full_name="C"),
            "d": make_player("WR", full_name="D"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("a", 100), fc_entry("b", 100), fc_entry("c", 200), fc_entry("d", 200)]
        )

        result = dc.evaluate_trade(roster, ["a"], ["c", "d"], players, fc_by_id, {}, league)

        assert [d["player_id"] for d in result["recommended_drops"]] == ["b"]

    def test_lineup_delta_after_drops_can_diverge_from_raw_lineup_delta(self):
        # One slot. Keep a (100), receive c (50): the forced cut must be a, since c is
        # incoming — a real loss the raw lineup_delta hides.
        league = {"roster_positions": ["WR"]}
        roster = {"players": ["a"], "taxi": [], "reserve": []}
        players = {
            "a": make_player("WR", full_name="A"),
            "c": make_player("WR", full_name="C"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("a", 100), fc_entry("c", 50)])

        result = dc.evaluate_trade(roster, [], ["c"], players, fc_by_id, {}, league)

        assert [d["player_id"] for d in result["recommended_drops"]] == ["a"]
        # Raw trade result: "a" (100) still wins the lone slot over "c" (50)
        # before any forced cut, so lineup_delta is 0 (no real change yet).
        assert result["lineup_delta"] == pytest.approx(0.0)
        # After cutting a, the lineup is just c (50).
        assert result["lineup_delta_after_drops"] == pytest.approx(-50.0)

    def test_recommends_multiple_drops_when_over_capacity_by_more_than_one(self):
        # Capacity 2: a=100, b=90, x=80 plus incoming c=500. Two cuts, lowest first, never c.
        league = {"roster_positions": ["WR", "BN"]}
        roster = {"players": ["a", "b", "x"], "taxi": [], "reserve": []}
        players = {
            "a": make_player("WR", full_name="A"),
            "b": make_player("WR", full_name="B"),
            "x": make_player("WR", full_name="X"),
            "c": make_player("WR", full_name="C"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("a", 100), fc_entry("b", 90), fc_entry("x", 80), fc_entry("c", 500)]
        )

        result = dc.evaluate_trade(roster, [], ["c"], players, fc_by_id, {}, league)

        assert [d["player_id"] for d in result["recommended_drops"]] == ["x", "b"]

    def test_lineup_delta_after_drops_matches_lineup_delta_when_no_drop_needed(self):
        league = {"roster_positions": ["WR", "BN"]}
        roster = {"players": ["old_wr"], "taxi": [], "reserve": []}
        players = {
            "old_wr": make_player("WR", full_name="Old WR"),
            "new_wr": make_player("WR", full_name="New WR"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("old_wr", 100), fc_entry("new_wr", 900)])

        result = dc.evaluate_trade(roster, ["old_wr"], ["new_wr"], players, fc_by_id, {}, league)

        assert result["recommended_drops"] == []
        assert result["lineup_delta_after_drops"] == pytest.approx(result["lineup_delta"])

    def test_pick_values_shift_asset_delta_without_touching_lineup_delta(self):
        league = {"roster_positions": ["WR", "BN"]}
        roster = {"players": ["a"], "taxi": [], "reserve": []}
        players = {"a": make_player("WR", full_name="A")}
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("a", 100)])

        no_picks = dc.evaluate_trade(roster, [], [], players, fc_by_id, {}, league)
        with_picks = dc.evaluate_trade(
            roster, [], [], players, fc_by_id, {}, league, outgoing_pick_value=50, incoming_pick_value=200
        )

        assert no_picks["asset_value_delta"] == pytest.approx(0)
        assert with_picks["asset_value_delta"] == pytest.approx(200 - 50)
        assert with_picks["lineup_delta"] == pytest.approx(no_picks["lineup_delta"])

    def test_existing_taxi_occupant_does_not_cause_a_false_over_capacity(self):
        # One starter plus one taxi stash: a 1-for-1 swap must not read as over capacity.
        league = {"roster_positions": ["WR", "BN", "BN"], "settings": {"taxi_slots": 2}}
        roster = {"players": ["starter_wr", "taxi_stash"], "taxi": ["taxi_stash"], "reserve": []}
        players = {
            "starter_wr": make_player("WR", full_name="Starter WR"),
            "taxi_stash": make_player("WR", full_name="Taxi Stash"),
            "incoming_wr": make_player("WR", full_name="Incoming WR"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("starter_wr", 100), fc_entry("taxi_stash", 50), fc_entry("incoming_wr", 900)]
        )

        result = dc.evaluate_trade(roster, ["starter_wr"], ["incoming_wr"], players, fc_by_id, {}, league)

        assert not result["over_capacity"]

    def test_trading_away_a_reserve_player_frees_that_slot_post_trade(self):
        # Trading away an IR player frees that slot.
        league = {"roster_positions": ["WR"], "settings": {"taxi_slots": 0}}
        roster = {
            "players": ["active_wr", "ir_wr"],
            "taxi": [],
            "reserve": ["ir_wr"],
        }
        players = {
            "active_wr": make_player("WR", full_name="Active WR"),
            "ir_wr": make_player("WR", full_name="IR WR"),
            "incoming_a": make_player("WR", full_name="Incoming A"),
            "incoming_b": make_player("WR", full_name="Incoming B"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [
                fc_entry("active_wr", 100),
                fc_entry("ir_wr", 50),
                fc_entry("incoming_a", 200),
                fc_entry("incoming_b", 200),
            ]
        )

        # Size after = 1 + 2 = 3 against capacity 1 (IR freed): over capacity, reserve_filled 0.
        result = dc.evaluate_trade(
            roster, ["ir_wr"], ["incoming_a", "incoming_b"], players, fc_by_id, {}, league
        )

        assert result["capacity"] == 1

    def test_the_other_side_of_the_same_trade_mirrors_asset_value_delta(self):
        # The swapped call's asset delta is the exact negative.
        league = {"roster_positions": ["WR", "BN"]}
        my_roster = {"players": ["low"], "taxi": [], "reserve": []}
        partner_roster = {"players": ["high"], "taxi": [], "reserve": []}
        players = {
            "low": make_player("WR", full_name="Low"),
            "high": make_player("WR", full_name="High"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("low", 100), fc_entry("high", 900)])

        my_side = dc.evaluate_trade(my_roster, ["low"], ["high"], players, fc_by_id, {}, league)
        partner_side = dc.evaluate_trade(partner_roster, ["high"], ["low"], players, fc_by_id, {}, league)

        assert my_side["asset_value_delta"] == pytest.approx(-partner_side["asset_value_delta"])


class TestEvaluateTradeCallouts:
    """Callouts: weekly gaps, handcuffs to kept RBs, bench-to-starter swaps, pick rank in class."""

    def test_omitting_handcuffs_and_pick_context_means_no_error_and_no_such_callouts(self):
        # Without handcuff/pick context, those callouts simply don't fire.
        league = {"roster_positions": ["WR", "BN"]}
        roster = {"players": ["old_wr"], "taxi": [], "reserve": []}
        players = {"old_wr": make_player("WR"), "new_wr": make_player("WR")}
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("old_wr", 100), fc_entry("new_wr", 200)])

        result = dc.evaluate_trade(roster, ["old_wr"], ["new_wr"], players, fc_by_id, {}, league)

        assert not any("handcuffs" in c or "remaining pick" in c for c in result["callouts"])

    def test_bye_gap_callout_fires_when_trade_opens_a_new_gap(self):
        league = {"roster_positions": ["WR", "BN"]}
        players = {
            "wr_keep": make_player("WR", team="AAA", full_name="Keep WR"),
            "wr_out": make_player("WR", team="BBB", full_name="Out WR"),
            "wr_in": make_player("WR", team="AAA", full_name="In WR"),  # same bye as wr_keep
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("wr_keep", 100), fc_entry("wr_out", 100), fc_entry("wr_in", 100)]
        )
        roster = {"players": ["wr_keep", "wr_out"], "taxi": [], "reserve": []}
        byes = {"AAA": 5, "BBB": 9}

        result = dc.evaluate_trade(roster, ["wr_out"], ["wr_in"], players, fc_by_id, byes, league)

        assert any("open a weekly starting gap in week(s) 5" in c for c in result["callouts"])
        assert result["weekly_gaps_opened"] == [5]
        assert result["weekly_gaps_closed"] == []

    def test_bye_gap_callout_fires_when_trade_closes_an_existing_gap(self):
        league = {"roster_positions": ["WR", "BN"]}
        players = {
            "wr_keep": make_player("WR", team="AAA", full_name="Keep WR"),
            "wr_out": make_player("WR", team="AAA", full_name="Out WR"),  # same bye as wr_keep
            "wr_in": make_player("WR", team="BBB", full_name="In WR"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("wr_keep", 100), fc_entry("wr_out", 100), fc_entry("wr_in", 100)]
        )
        roster = {"players": ["wr_keep", "wr_out"], "taxi": [], "reserve": []}
        byes = {"AAA": 5, "BBB": 9}

        result = dc.evaluate_trade(roster, ["wr_out"], ["wr_in"], players, fc_by_id, byes, league)

        assert any("close an existing weekly starting gap in week(s) 5" in c for c in result["callouts"])
        assert result["weekly_gaps_closed"] == [5]
        assert result["weekly_gaps_opened"] == []

    def test_weekly_gap_fields_are_populated_even_when_compute_callouts_is_false(self):
        # Gap lists are computed even with compute_callouts=False; offer ranking needs them.
        league = {"roster_positions": ["WR", "BN"]}
        players = {
            "wr_keep": make_player("WR", team="AAA", full_name="Keep WR"),
            "wr_out": make_player("WR", team="BBB", full_name="Out WR"),
            "wr_in": make_player("WR", team="AAA", full_name="In WR"),  # same bye as wr_keep
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("wr_keep", 100), fc_entry("wr_out", 100), fc_entry("wr_in", 100)]
        )
        roster = {"players": ["wr_keep", "wr_out"], "taxi": [], "reserve": []}
        byes = {"AAA": 5, "BBB": 9}

        result = dc.evaluate_trade(
            roster, ["wr_out"], ["wr_in"], players, fc_by_id, byes, league, compute_callouts=False
        )

        assert result["callouts"] == []
        assert result["weekly_gaps_opened"] == [5]

    def test_handcuff_callout_fires_for_an_incoming_backup_to_a_kept_starter(self):
        league = {"roster_positions": ["RB", "BN"]}
        players = {
            "rb_starter": make_player("RB", full_name="Starter RB"),
            "hc_backup": make_player("RB", full_name="Backup RB"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("rb_starter", 300), fc_entry("hc_backup", 20)])
        roster = {"players": ["rb_starter"], "taxi": [], "reserve": []}
        handcuffs = {"rb_starter": "hc_backup"}

        result = dc.evaluate_trade(
            roster, [], ["hc_backup"], players, fc_by_id, {}, league, handcuffs=handcuffs
        )

        assert any("handcuffs your own Starter RB" in c for c in result["callouts"])

    def test_buried_bench_and_instant_starter_callouts(self):
        league = {"roster_positions": ["WR", "BN"]}
        players = {
            "starter_wr": make_player("WR", full_name="Starter WR"),
            "bench_wr": make_player("WR", full_name="Bench WR"),
            "new_wr": make_player("WR", full_name="New WR"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("starter_wr", 500), fc_entry("bench_wr", 100), fc_entry("new_wr", 900)]
        )
        roster = {"players": ["starter_wr", "bench_wr"], "taxi": [], "reserve": []}

        result = dc.evaluate_trade(roster, ["bench_wr"], ["new_wr"], players, fc_by_id, {}, league)

        assert any("Bench WR wasn't even starting for you" in c for c in result["callouts"])
        assert any("New WR would start for you immediately" in c for c in result["callouts"])

    def test_pick_context_callout_ranks_within_the_picks_own_class(self):
        league = {"roster_positions": ["WR", "BN"]}
        roster = {"players": [], "taxi": [], "reserve": []}
        players: dict[str, dict] = {}
        fc_by_id: dict[str, dict] = {}
        pick_value_table = pd.DataFrame(
            [
                {"pick": "2026 Pick 1.01", "owner": "x", "owner_roster_id": 1, "value": 500},
                {"pick": "2026 Pick 1.02", "owner": "x", "owner_roster_id": 1, "value": 300},
                {"pick": "2026 Pick 2.05", "owner": "x", "owner_roster_id": 1, "value": 50},
                {"pick": "2027 Pick 1.01", "owner": "x", "owner_roster_id": 1, "value": 400},
            ]
        )

        result = dc.evaluate_trade(
            roster, [], [], players, fc_by_id, {}, league,
            outgoing_pick_value=300, outgoing_pick_names=["2026 Pick 1.02"], pick_value_table=pick_value_table,
        )

        # #2 within the 2026 class specifically (500 > 300 > 50), not #2
        # across the whole table (which also has the 2027 pick).
        assert any(
            "2026 Pick 1.02 is currently the #2 remaining pick in the 2026 class (value 300)" in c
            for c in result["callouts"]
        )

    def test_pick_context_callout_handles_next_seasons_round_only_pick_name_format(self):
        # Next-season names ("2027 1st") have no " Pick "; the class comes from the leading year.
        league = {"roster_positions": ["WR", "BN"]}
        roster = {"players": [], "taxi": [], "reserve": []}
        players: dict[str, dict] = {}
        fc_by_id: dict[str, dict] = {}
        pick_value_table = pd.DataFrame(
            [
                {"pick": "2027 1st", "owner": "x", "owner_roster_id": 1, "value": 400},
                {"pick": "2027 2nd", "owner": "x", "owner_roster_id": 1, "value": 250},
                {"pick": "2026 Pick 1.01", "owner": "x", "owner_roster_id": 1, "value": 500},
            ]
        )

        result = dc.evaluate_trade(
            roster, [], [], players, fc_by_id, {}, league,
            outgoing_pick_value=250, outgoing_pick_names=["2027 2nd"], pick_value_table=pick_value_table,
        )

        # #2 within the 2027 class (400 > 250), not stranded alone at #1 in
        # a one-row class named after its own full pick name.
        assert any(
            "2027 2nd is currently the #2 remaining pick in the 2027 class (value 250)" in c
            for c in result["callouts"]
        )

    def test_pick_context_callout_does_not_crash_on_a_pick_name_with_no_leading_year(self):
        # A name without a leading year forms its own group instead of breaking the rank cast.
        league = {"roster_positions": ["WR", "BN"]}
        roster = {"players": [], "taxi": [], "reserve": []}
        players: dict[str, dict] = {}
        fc_by_id: dict[str, dict] = {}
        pick_value_table = pd.DataFrame(
            [{"pick": "weird_pick_name", "owner": "x", "owner_roster_id": 1, "value": 100}]
        )

        result = dc.evaluate_trade(
            roster, [], [], players, fc_by_id, {}, league,
            outgoing_pick_value=100, outgoing_pick_names=["weird_pick_name"], pick_value_table=pick_value_table,
        )

        assert any("weird_pick_name is currently the #1 remaining pick" in c for c in result["callouts"])


class TestFindTradeOffers:
    """Offer search: partner tolerance is the only gate; need match only breaks ties."""

    def test_worth_pursuing_matches_a_direct_zero_outgoing_evaluate_trade_call(self):
        league = {"roster_positions": ["WR", "BN"]}
        your_roster = {"roster_id": 1, "players": ["starter_wr"], "taxi": [], "reserve": []}
        partner_roster = {"players": ["target_wr"], "taxi": [], "reserve": []}
        players = {
            "starter_wr": make_player("WR", full_name="Starter WR"),
            "target_wr": make_player("WR", full_name="Target WR"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("starter_wr", 200), fc_entry("target_wr", 100)])
        replacement_level = {"QB": 0.0, "RB": 0.0, "WR": 50.0, "TE": 0.0}

        result = dc.find_trade_offers(
            your_roster, partner_roster, players, fc_by_id, {}, league, replacement_level, EMPTY_PICKS,
            target_player_id="target_wr",
        )

        expected = dc.evaluate_trade(your_roster, [], ["target_wr"], players, fc_by_id, {}, league)
        assert result["target_read"] == expected

    def test_raises_when_neither_or_both_targets_given(self):
        league = {"roster_positions": ["WR", "BN"]}
        your_roster = {"roster_id": 1, "players": [], "taxi": [], "reserve": []}
        partner_roster = {"players": [], "taxi": [], "reserve": []}
        replacement_level = {"QB": 0.0, "RB": 0.0, "WR": 0.0, "TE": 0.0}

        with pytest.raises(ValueError):
            dc.find_trade_offers(your_roster, partner_roster, {}, {}, {}, league, replacement_level, EMPTY_PICKS)
        with pytest.raises(ValueError):
            dc.find_trade_offers(
                your_roster, partner_roster, {}, {}, {}, league, replacement_level, EMPTY_PICKS,
                target_player_id="a", target_pick_name="b",
            )

    def test_clean_one_for_one_surfaces_the_obvious_combo(self):
        # Your only sellable candidate ("depth_wr") is worth about the same
        # as the target - the one plausible combo should surface as-is.
        league = {"roster_positions": ["WR", "BN"]}
        your_roster = {"roster_id": 1, "players": ["starter_wr", "depth_wr"], "taxi": [], "reserve": []}
        partner_roster = {"players": ["target_wr"], "taxi": [], "reserve": []}
        players = {
            "starter_wr": make_player("WR", full_name="Starter WR"),
            "depth_wr": make_player("WR", full_name="Depth WR"),
            "target_wr": make_player("WR", full_name="Target WR"),
        }
        players["starter_wr"]["years_exp"] = 5
        players["depth_wr"]["years_exp"] = 3
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("starter_wr", 500), fc_entry("depth_wr", 100), fc_entry("target_wr", 100)]
        )
        replacement_level = {"QB": 0.0, "RB": 0.0, "WR": 50.0, "TE": 0.0}

        result = dc.find_trade_offers(
            your_roster, partner_roster, players, fc_by_id, {}, league, replacement_level, EMPTY_PICKS,
            target_player_id="target_wr",
        )

        assert len(result["offers"]) == 1
        assert [asset["id"] for asset in result["offers"][0]["combo"]] == ["depth_wr"]

    def test_returned_offers_carry_real_callouts_not_the_stripped_search_pass(self):
        # Returned offers are re-evaluated with callouts; depth_wr never starts, so giving it
        # up shows "wasn't even starting".
        league = {"roster_positions": ["WR", "BN"]}
        your_roster = {"roster_id": 1, "players": ["starter_wr", "depth_wr"], "taxi": [], "reserve": []}
        partner_roster = {"players": ["target_wr"], "taxi": [], "reserve": []}
        players = {
            "starter_wr": make_player("WR", full_name="Starter WR"),
            "depth_wr": make_player("WR", full_name="Depth WR"),
            "target_wr": make_player("WR", full_name="Target WR"),
        }
        players["starter_wr"]["years_exp"] = 5
        players["depth_wr"]["years_exp"] = 3
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("starter_wr", 500), fc_entry("depth_wr", 100), fc_entry("target_wr", 100)]
        )
        replacement_level = {"QB": 0.0, "RB": 0.0, "WR": 50.0, "TE": 0.0}

        result = dc.find_trade_offers(
            your_roster, partner_roster, players, fc_by_id, {}, league, replacement_level, EMPTY_PICKS,
            target_player_id="target_wr",
        )

        assert any(
            "Depth WR wasn't even starting for you" in c
            for c in result["offers"][0]["your_side"]["callouts"]
        )

    def test_lopsided_combo_is_filtered_even_when_cheap_for_you(self):
        # cheap_wr (120) for target_wr (200) is great for you but outside the partner's tolerance.
        league = {"roster_positions": ["WR", "BN"]}
        your_roster = {"roster_id": 1, "players": ["starter_wr", "cheap_wr"], "taxi": [], "reserve": []}
        partner_roster = {"players": ["target_wr"], "taxi": [], "reserve": []}
        players = {
            "starter_wr": make_player("WR", full_name="Starter WR"),
            "cheap_wr": make_player("WR", full_name="Cheap WR"),
            "target_wr": make_player("WR", full_name="Target WR"),
        }
        players["starter_wr"]["years_exp"] = 5
        players["cheap_wr"]["years_exp"] = 3
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("starter_wr", 500), fc_entry("cheap_wr", 120), fc_entry("target_wr", 200)]
        )
        replacement_level = {"QB": 0.0, "RB": 0.0, "WR": 50.0, "TE": 0.0}

        one_sided = dc.evaluate_trade(your_roster, ["cheap_wr"], ["target_wr"], players, fc_by_id, {}, league)
        assert one_sided["asset_value_delta"] > 0  # looks like a steal for you alone

        result = dc.find_trade_offers(
            your_roster, partner_roster, players, fc_by_id, {}, league, replacement_level, EMPTY_PICKS,
            target_player_id="target_wr",
        )

        assert result["offers"] == []

    def test_no_viable_offer_returns_empty_list_not_a_forced_pick(self):
        league = {"roster_positions": ["WR", "BN"]}
        your_roster = {"roster_id": 1, "players": ["starter_wr", "low_wr"], "taxi": [], "reserve": []}
        partner_roster = {"players": ["target_wr"], "taxi": [], "reserve": []}
        players = {
            "starter_wr": make_player("WR", full_name="Starter WR"),
            "low_wr": make_player("WR", full_name="Low WR"),
            "target_wr": make_player("WR", full_name="Target WR"),
        }
        players["starter_wr"]["years_exp"] = 5
        players["low_wr"]["years_exp"] = 3
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("starter_wr", 500), fc_entry("low_wr", 110), fc_entry("target_wr", 200)]
        )
        replacement_level = {"QB": 0.0, "RB": 0.0, "WR": 50.0, "TE": 0.0}

        result = dc.find_trade_offers(
            your_roster, partner_roster, players, fc_by_id, {}, league, replacement_level, EMPTY_PICKS,
            target_player_id="target_wr",
        )

        assert result["offers"] == []
        assert result["combos_evaluated"] > 0  # it searched - it just found nothing plausible

    def test_combo_touching_a_partner_need_is_ranked_first_among_equally_plausible_options(self):
        # Two tied 100-value combos; the partner needs RB, so the RB combo ranks first.
        league = {"roster_positions": ["WR", "RB", "BN", "BN"]}
        your_roster = {
            "roster_id": 1,
            "players": ["starter_wr", "wr_offer", "starter_rb", "rb_offer"],
            "taxi": [],
            "reserve": [],
        }
        partner_roster = {"players": ["target_wr", "partner_rb", "partner_wr2"], "taxi": [], "reserve": []}
        players = {
            "starter_wr": make_player("WR", full_name="Starter WR"),
            "wr_offer": make_player("WR", full_name="WR Offer"),
            "starter_rb": make_player("RB", full_name="Starter RB"),
            "rb_offer": make_player("RB", full_name="RB Offer"),
            "target_wr": make_player("WR", full_name="Target WR"),
            "partner_rb": make_player("RB", full_name="Partner RB"),
            "partner_wr2": make_player("WR", full_name="Partner WR 2"),
        }
        players["starter_wr"]["years_exp"] = 5
        players["wr_offer"]["years_exp"] = 3
        players["starter_rb"]["years_exp"] = 5
        players["rb_offer"]["years_exp"] = 3
        players["target_wr"]["years_exp"] = 1  # young, keeps partner's WR position off the need list
        players["partner_rb"]["years_exp"] = 5  # not young - partner's lone RB has no young core
        players["partner_wr2"]["years_exp"] = 1
        fc_by_id = dc.fc_value_by_sleeper_id(
            [
                fc_entry("starter_wr", 500),
                fc_entry("wr_offer", 100),
                fc_entry("starter_rb", 500),
                fc_entry("rb_offer", 100),
                fc_entry("target_wr", 100),
                fc_entry("partner_rb", 50),
                fc_entry("partner_wr2", 50),
            ]
        )
        replacement_level = {"QB": 0.0, "RB": 50.0, "WR": 50.0, "TE": 0.0}

        result = dc.find_trade_offers(
            your_roster, partner_roster, players, fc_by_id, {}, league, replacement_level, EMPTY_PICKS,
            target_player_id="target_wr",
        )

        best = result["offers"][0]
        assert [asset["id"] for asset in best["combo"]] == ["rb_offer"]
        assert best["partner_need_match"] is True
        assert best["partner_need_positions"] == frozenset({"RB"})

    def test_pool_and_combo_size_bounds_cap_the_search_regardless_of_pool_size(self):
        # 30 picks, no players: the pool still caps before combos are built.
        league = {"roster_positions": ["WR", "BN"]}
        your_roster = {"roster_id": 1, "players": [], "taxi": [], "reserve": []}
        partner_roster = {"players": ["target_wr"], "taxi": [], "reserve": []}
        players = {"target_wr": make_player("WR", full_name="Target WR")}
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("target_wr", 100)])
        replacement_level = {"QB": 0.0, "RB": 0.0, "WR": 0.0, "TE": 0.0}
        pick_value_table = pd.DataFrame(
            [{"pick": f"pick_{i}", "owner": "You", "owner_roster_id": 1, "value": 100 + i} for i in range(30)]
        )

        result = dc.find_trade_offers(
            your_roster, partner_roster, players, fc_by_id, {}, league, replacement_level, pick_value_table,
            target_player_id="target_wr",
        )

        expected_combo_count = sum(
            math.comb(dc.TRADE_OFFER_POOL_CAP, size) for size in range(1, dc.TRADE_OFFER_MAX_COMBO_SIZE + 1)
        )
        assert result["combos_considered"] == expected_combo_count

    def test_pool_prunes_out_of_band_candidates_before_capping_so_a_low_value_target_still_finds_a_match(self):
        # 15 picks at 500 plus 5 cheap picks near a 30-value target: pruning out-of-band assets
        # before the cap keeps the cheap ones.
        league = {"roster_positions": ["WR", "BN"]}
        your_roster = {"roster_id": 1, "players": [], "taxi": [], "reserve": []}
        partner_roster = {"players": ["target_wr"], "taxi": [], "reserve": []}
        players = {"target_wr": make_player("WR", full_name="Target WR")}
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("target_wr", 30)])
        replacement_level = {"QB": 0.0, "RB": 0.0, "WR": 0.0, "TE": 0.0}
        expensive = [{"pick": f"expensive_{i}", "owner": "You", "owner_roster_id": 1, "value": 500} for i in range(15)]
        cheap = [{"pick": f"cheap_{i}", "owner": "You", "owner_roster_id": 1, "value": 20 + i * 2} for i in range(5)]
        pick_value_table = pd.DataFrame(expensive + cheap)

        result = dc.find_trade_offers(
            your_roster, partner_roster, players, fc_by_id, {}, league, replacement_level, pick_value_table,
            target_player_id="target_wr",
        )

        assert result["offers"] != []
        assert all(asset["id"].startswith("cheap_") for offer in result["offers"] for asset in offer["combo"])

    def test_unresolved_player_target_returns_no_offers_without_a_fabricated_zero_baseline(self):
        # An unranked target isn't worth $0; no search should run.
        league = {"roster_positions": ["WR", "BN"]}
        your_roster = {"roster_id": 1, "players": ["depth_wr"], "taxi": [], "reserve": []}
        partner_roster = {"players": ["unranked_target"], "taxi": [], "reserve": []}
        players = {
            "depth_wr": make_player("WR", full_name="Depth WR"),
            "unranked_target": make_player("WR", full_name="Unranked Target"),
        }
        players["depth_wr"]["years_exp"] = 3
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("depth_wr", 5)])
        replacement_level = {"QB": 0.0, "RB": 0.0, "WR": 0.0, "TE": 0.0}

        result = dc.find_trade_offers(
            your_roster, partner_roster, players, fc_by_id, {}, league, replacement_level, EMPTY_PICKS,
            target_player_id="unranked_target",
        )

        assert result["target_value_resolved"] is False
        assert result["offers"] == []
        assert result["combos_considered"] == 0
        assert result["combos_evaluated"] == 0

    def test_unresolved_pick_target_does_not_propagate_nan(self):
        # An unmatched pick name carries NaN, which `or 0.0` wouldn't catch.
        league = {"roster_positions": ["WR", "BN"]}
        your_roster = {"roster_id": 1, "players": [], "taxi": [], "reserve": []}
        partner_roster = {"players": [], "taxi": [], "reserve": []}
        pick_value_table = pd.DataFrame(
            [{"pick": "2027 1st", "owner": "Them", "owner_roster_id": 2, "value": float("nan")}]
        )
        replacement_level = {"QB": 0.0, "RB": 0.0, "WR": 0.0, "TE": 0.0}

        result = dc.find_trade_offers(
            your_roster, partner_roster, {}, {}, {}, league, replacement_level, pick_value_table,
            target_pick_name="2027 1st",
        )

        assert result["target_value_resolved"] is False
        assert result["target_value"] == 0.0
        assert result["offers"] == []
        assert not math.isnan(result["target_read"]["asset_value_delta"])

    def test_unmatched_sellable_player_falls_back_to_zero_value_not_nan(self):
        # An unranked sellable player's NaN value falls back to 0.0.
        league = {"roster_positions": ["WR", "BN"]}
        your_roster = {
            "roster_id": 1,
            "players": ["starter_wr", "priced_wr", "unmatched_wr"],
            "taxi": [],
            "reserve": [],
        }
        partner_roster = {"players": ["target_wr"], "taxi": [], "reserve": []}
        players = {
            "starter_wr": make_player("WR", full_name="Starter WR"),
            "priced_wr": make_player("WR", full_name="Priced WR"),
            "unmatched_wr": make_player("WR", full_name="Unmatched WR"),
            "target_wr": make_player("WR", full_name="Target WR"),
        }
        players["priced_wr"]["years_exp"] = 3
        players["unmatched_wr"]["years_exp"] = 3
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("starter_wr", 500), fc_entry("priced_wr", 150), fc_entry("target_wr", 150)]
        )  # unmatched_wr deliberately has no FantasyCalc entry
        replacement_level = {"QB": 0.0, "RB": 0.0, "WR": 50.0, "TE": 0.0}

        result = dc.find_trade_offers(
            your_roster, partner_roster, players, fc_by_id, {}, league, replacement_level, EMPTY_PICKS,
            target_player_id="target_wr",
        )

        assert any(a["id"] == "unmatched_wr" for offer in result["offers"] for a in offer["combo"])
        assert not any(math.isnan(a["value"]) for offer in result["offers"] for a in offer["combo"])

    def test_handcuffs_and_pick_value_table_pass_through_to_target_read_callouts(self):
        # Handcuffs and pick values reach the returned offers' callouts.
        league = {"roster_positions": ["RB", "BN"]}
        your_roster = {"roster_id": 1, "players": ["rb_starter"], "taxi": [], "reserve": []}
        partner_roster = {"players": ["hc_backup"], "taxi": [], "reserve": []}
        players = {
            "rb_starter": make_player("RB", full_name="Starter RB"),
            "hc_backup": make_player("RB", full_name="Backup RB"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("rb_starter", 300), fc_entry("hc_backup", 20)])
        handcuffs = {"rb_starter": "hc_backup"}
        replacement_level = {"QB": 0.0, "RB": 0.0, "WR": 0.0, "TE": 0.0}

        result = dc.find_trade_offers(
            your_roster, partner_roster, players, fc_by_id, {}, league, replacement_level, EMPTY_PICKS,
            handcuffs=handcuffs, target_player_id="hc_backup",
        )

        assert any("handcuffs your own Starter RB" in c for c in result["target_read"]["callouts"])


def _sellable_of(*values: float) -> pd.DataFrame:
    """A minimal sellable_players()-shaped DataFrame for affordability-ceiling tests -
    only adj_value is read by _max_affordable_target_value/leaguewide_trade_candidates."""
    return pd.DataFrame({"adj_value": list(values)})


class TestMaxAffordableTargetValue:
    """Ceiling = top `TRADE_OFFER_MAX_COMBO_SIZE` assets × `TRADE_OFFER_PREFILTER_HIGH`."""

    def test_ceiling_is_top_combo_size_assets_scaled_by_prefilter_high(self):
        sellable = _sellable_of(100, 80, 60, 10)  # only the top 3 count

        ceiling = dc._max_affordable_target_value(sellable, EMPTY_PICKS, roster_id=1)

        assert ceiling == pytest.approx((100 + 80 + 60) * dc.TRADE_OFFER_PREFILTER_HIGH)

    def test_picks_are_combined_with_players_for_the_top_combo(self):
        sellable = _sellable_of(100)
        picks = pd.DataFrame(
            [
                {"pick": "p1", "owner": "You", "owner_roster_id": 1, "value": 90},
                {"pick": "p2", "owner": "You", "owner_roster_id": 1, "value": 5},
            ]
        )

        ceiling = dc._max_affordable_target_value(sellable, picks, roster_id=1)

        # Top 3 of {100, 90, 5}: 100 + 90 + 5 = 195.
        assert ceiling == pytest.approx(195 * dc.TRADE_OFFER_PREFILTER_HIGH)

    def test_picks_owned_by_a_different_roster_are_excluded(self):
        sellable = _sellable_of(100)
        picks = pd.DataFrame([{"pick": "p1", "owner": "Them", "owner_roster_id": 2, "value": 900}])

        ceiling = dc._max_affordable_target_value(sellable, picks, roster_id=1)

        assert ceiling == pytest.approx(100 * dc.TRADE_OFFER_PREFILTER_HIGH)

    def test_columnless_empty_sellable_pool_does_not_crash(self):
        # An empty sellable frame has no columns.
        ceiling = dc._max_affordable_target_value(pd.DataFrame([]), EMPTY_PICKS, roster_id=1)

        assert ceiling == 0.0


class TestLeaguewideTradeCandidates:
    """Other teams' players ranked by marginal value, filtered to what you can afford."""

    LEAGUE = {"roster_positions": ["WR", "BN", "BN"]}

    def test_excludes_the_users_own_roster_players(self):
        user_roster = {"roster_id": 1, "players": ["user_wr"], "taxi": [], "reserve": []}
        rosters = [user_roster, {"roster_id": 2, "players": ["user_wr"]}]  # same id, hypothetically duplicated
        players = {"user_wr": make_player("WR", full_name="User WR")}
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("user_wr", 100)])
        sellable = _sellable_of(1000)  # affordability ceiling is not the point of this test

        candidates = dc.leaguewide_trade_candidates(
            rosters, user_roster, players, fc_by_id, {}, self.LEAGUE, sellable, EMPTY_PICKS
        )

        assert candidates == []

    def test_excludes_candidates_priced_above_the_affordability_ceiling(self):
        user_roster = {"roster_id": 1, "players": ["user_wr"], "taxi": [], "reserve": []}
        rosters = [user_roster, {"roster_id": 2, "players": ["expensive_wr"]}]
        players = {
            "user_wr": make_player("WR", full_name="User WR"),
            "expensive_wr": make_player("WR", full_name="Expensive WR"),
        }
        # expensive_wr (1000) is a big upgrade but over the 200 affordability cap.
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("user_wr", 100), fc_entry("expensive_wr", 1000)])
        sellable = _sellable_of(100)

        candidates = dc.leaguewide_trade_candidates(
            rosters, user_roster, players, fc_by_id, {}, self.LEAGUE, sellable, EMPTY_PICKS
        )

        assert candidates == []

    def test_filters_to_positive_marginal_value_only(self):
        user_roster = {"roster_id": 1, "players": ["user_wr"], "taxi": [], "reserve": []}
        rosters = [user_roster, {"roster_id": 2, "players": ["worse_wr"]}]
        players = {
            "user_wr": make_player("WR", full_name="User WR"),
            "worse_wr": make_player("WR", full_name="Worse WR"),
        }
        # worse_wr (10) is affordable, but strictly worse than the user's own
        # starter (100) - adding it can't raise the starting lineup's value.
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("user_wr", 100), fc_entry("worse_wr", 10)])
        sellable = _sellable_of(1000)

        candidates = dc.leaguewide_trade_candidates(
            rosters, user_roster, players, fc_by_id, {}, self.LEAGUE, sellable, EMPTY_PICKS
        )

        assert candidates == []

    def test_affordable_positive_value_candidate_is_returned_with_its_owning_roster_id(self):
        user_roster = {"roster_id": 1, "players": ["user_wr"], "taxi": [], "reserve": []}
        rosters = [user_roster, {"roster_id": 2, "players": ["good_wr"]}]
        players = {
            "user_wr": make_player("WR", full_name="User WR"),
            "good_wr": make_player("WR", full_name="Good WR"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("user_wr", 100), fc_entry("good_wr", 300)])
        sellable = _sellable_of(1000)

        candidates = dc.leaguewide_trade_candidates(
            rosters, user_roster, players, fc_by_id, {}, self.LEAGUE, sellable, EMPTY_PICKS
        )

        assert len(candidates) == 1
        assert candidates[0]["player_id"] == "good_wr"
        assert candidates[0]["roster_id"] == 2
        assert candidates[0]["marginal_value"] > 0

    def test_respects_top_n(self):
        user_roster = {"roster_id": 1, "players": ["user_wr"], "taxi": [], "reserve": []}
        other_rosters = [
            {"roster_id": i, "players": [f"good_wr_{i}"]} for i in range(2, 6)  # 4 affordable, positive candidates
        ]
        rosters = [user_roster] + other_rosters
        players = {"user_wr": make_player("WR", full_name="User WR")}
        fc_entries = [fc_entry("user_wr", 100)]
        for i in range(2, 6):
            pid = f"good_wr_{i}"
            players[pid] = make_player("WR", full_name=pid)
            fc_entries.append(fc_entry(pid, 200 + i))
        fc_by_id = dc.fc_value_by_sleeper_id(fc_entries)
        sellable = _sellable_of(1000)

        candidates = dc.leaguewide_trade_candidates(
            rosters, user_roster, players, fc_by_id, {}, self.LEAGUE, sellable, EMPTY_PICKS, top_n=2
        )

        assert len(candidates) == 2


class TestSuggestedTrades:
    """Stage 2: keep candidates with a positive-lineup best offer, ranked by that gain."""

    LEAGUE = {"roster_positions": ["WR", "BN", "BN", "BN"]}

    def _base_roster_and_players(self) -> tuple[dict, dict, dict]:
        your_roster = {"roster_id": 1, "players": ["starter_wr", "depth_wr", "depth_wr2"], "taxi": [], "reserve": []}
        players = {
            "starter_wr": make_player("WR", full_name="Starter WR"),
            "depth_wr": make_player("WR", full_name="Depth WR"),
            "depth_wr2": make_player("WR", full_name="Depth WR 2"),
        }
        players["starter_wr"]["years_exp"] = 5
        players["depth_wr"]["years_exp"] = 3
        players["depth_wr2"]["years_exp"] = 3
        return your_roster, players, {"QB": 0.0, "RB": 0.0, "WR": 10.0, "TE": 0.0}

    def test_drops_candidates_with_no_viable_offer_or_non_positive_lineup_gain(self):
        your_roster, players, replacement_level = self._base_roster_and_players()
        # target_a (100): viable but no lineup gain (never beats starter_wr), dropped.
        # target_c (220): depth_wr + depth_wr2 (210) clears tolerance, +70 lineup, kept.
        # target_huge: nothing is in range, no offer.
        partner_a = {"roster_id": 2, "players": ["target_a"]}
        partner_c = {"roster_id": 3, "players": ["target_c"]}
        partner_huge = {"roster_id": 4, "players": ["target_huge"]}
        players["target_a"] = make_player("WR", full_name="Target A")
        players["target_c"] = make_player("WR", full_name="Target C")
        players["target_huge"] = make_player("WR", full_name="Target Huge")
        fc_by_id = dc.fc_value_by_sleeper_id(
            [
                fc_entry("starter_wr", 150),
                fc_entry("depth_wr", 100),
                fc_entry("depth_wr2", 110),
                fc_entry("target_a", 100),
                fc_entry("target_c", 220),
                fc_entry("target_huge", 100_000),
            ]
        )
        rosters_by_id = {1: your_roster, 2: partner_a, 3: partner_c, 4: partner_huge}
        candidates = [
            {"player_id": "target_a", "roster_id": 2, "marginal_value": 1.0, "drop": None},
            {"player_id": "target_c", "roster_id": 3, "marginal_value": 2.0, "drop": None},
            {"player_id": "target_huge", "roster_id": 4, "marginal_value": 3.0, "drop": None},
        ]

        results = dc.suggested_trades(
            your_roster, rosters_by_id, players, fc_by_id, {}, self.LEAGUE, replacement_level, EMPTY_PICKS, candidates
        )

        assert [r["target_player_id"] for r in results] == ["target_c"]
        assert results[0]["offers"][0]["your_side"]["lineup_delta_after_drops"] == pytest.approx(70.0)
        assert results[0]["roster_id"] == 3

    def test_respects_top_n(self):
        your_roster, players, replacement_level = self._base_roster_and_players()
        rosters_by_id = {1: your_roster}
        # Same as target_c above: a viable +70 offer.
        fc_entries = [fc_entry("starter_wr", 150), fc_entry("depth_wr", 100), fc_entry("depth_wr2", 110)]
        candidates = []
        for i in range(2, 6):  # 4 viable, equally-easy targets
            pid = f"target_{i}"
            players[pid] = make_player("WR", full_name=pid)
            fc_entries.append(fc_entry(pid, 220))
            rosters_by_id[i] = {"roster_id": i, "players": [pid]}
            candidates.append({"player_id": pid, "roster_id": i, "marginal_value": 1.0, "drop": None})
        fc_by_id = dc.fc_value_by_sleeper_id(fc_entries)

        results = dc.suggested_trades(
            your_roster,
            rosters_by_id,
            players,
            fc_by_id,
            {},
            self.LEAGUE,
            replacement_level,
            EMPTY_PICKS,
            candidates,
            top_n=2,
        )

        assert len(results) == 2

    def test_ties_on_lineup_gain_are_broken_by_net_weekly_gap_improvement(self, monkeypatch):
        # Stubbed to isolate the ranking and tiebreak; find_trade_offers has its own tests.
        your_roster, players, replacement_level = self._base_roster_and_players()
        rosters_by_id = {
            1: your_roster,
            2: {"roster_id": 2, "players": ["target_a"]},
            3: {"roster_id": 3, "players": ["target_b"]},
        }
        candidates = [
            {"player_id": "target_a", "roster_id": 2, "marginal_value": 1.0, "drop": None},
            {"player_id": "target_b", "roster_id": 3, "marginal_value": 2.0, "drop": None},
        ]
        # Equal +70 gains: target_a closes a gap, target_b opens one, so a ranks first
        # regardless of input order.
        gaps_by_target = {
            "target_a": {"weekly_gaps_opened": [], "weekly_gaps_closed": [5]},
            "target_b": {"weekly_gaps_opened": [9], "weekly_gaps_closed": []},
        }

        def fake_find_trade_offers(
            your_roster,
            partner_roster,
            players,
            fc_by_sleeper_id,
            byes,
            league,
            replacement_level,
            pick_value_table,
            handcuffs=None,
            target_player_id=None,
            target_pick_name=None,
            top_n=3,
        ):
            your_side = {"lineup_delta_after_drops": 70.0, **gaps_by_target[target_player_id]}
            return {"offers": [{"your_side": your_side, "combo": []}]}

        monkeypatch.setattr(trade_module, "find_trade_offers", fake_find_trade_offers)

        results = dc.suggested_trades(
            your_roster, rosters_by_id, players, {}, {}, self.LEAGUE, replacement_level, EMPTY_PICKS, candidates
        )

        assert [r["target_player_id"] for r in results] == ["target_a", "target_b"]


def _scripted_evaluate_trade(script):
    """Fake `evaluate_trade()` keyed by (roster_id, sorted assets each way).

    Unscripted variants return (0.0, 0.0), which fails `_is_good`.
    """

    def fake(
        roster,
        outgoing_player_ids,
        incoming_player_ids,
        players,
        fc_by_sleeper_id,
        byes,
        league,
        outgoing_pick_value=0.0,
        incoming_pick_value=0.0,
        handcuffs=None,
        outgoing_pick_names=None,
        incoming_pick_names=None,
        pick_value_table=None,
        compute_callouts=True,
    ):
        key = (
            roster["roster_id"],
            tuple(sorted(outgoing_player_ids)),
            tuple(sorted(outgoing_pick_names or [])),
            tuple(sorted(incoming_player_ids)),
            tuple(sorted(incoming_pick_names or [])),
        )
        scripted = script.get(key, {})
        return {
            "lineup_delta": scripted.get("lineup_delta_after_drops", 0.0),
            "lineup_delta_after_drops": scripted.get("lineup_delta_after_drops", 0.0),
            "asset_value_delta": scripted.get("asset_value_delta", 0.0),
            "over_capacity": False,
            "roster_size_after": 0,
            "capacity": 0,
            "recommended_drops": [],
            "callouts": [],
        }

    return fake


class TestAssetPool:
    """Sellable players plus owned picks, merged, value-sorted, and capped."""

    def test_merges_sellable_players_and_owned_picks_sorted_by_value(self):
        league = {"roster_positions": ["WR", "BN"]}
        roster = {"roster_id": 1, "players": ["starter_wr", "depth_wr"]}
        players = {
            "starter_wr": make_player("WR", full_name="Starter WR"),
            "depth_wr": make_player("WR", full_name="Depth WR"),
        }
        players["starter_wr"]["years_exp"] = 5
        players["depth_wr"]["years_exp"] = 3
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("starter_wr", 500), fc_entry("depth_wr", 100)])
        replacement_level = {"QB": 0.0, "RB": 0.0, "WR": 50.0, "TE": 0.0}
        pick_values = pd.DataFrame([{"pick": "2026 Pick 1.05", "owner": "Me", "owner_roster_id": 1, "value": 60.0}])

        pool = trade_module._asset_pool(roster, players, fc_by_id, replacement_level, league, {}, pick_values)

        assert {c["id"] for c in pool} == {"depth_wr", "2026 Pick 1.05"}
        assert pool[0]["id"] == "depth_wr"  # depth_wr (~100) outranks the pick (60)

    def test_value_cap_excludes_pricier_candidates(self):
        league = {"roster_positions": ["WR", "BN", "BN"]}
        roster = {"roster_id": 1, "players": ["starter_wr", "depth_wr", "depth_wr2"]}
        players = {
            "starter_wr": make_player("WR", full_name="Starter WR"),
            "depth_wr": make_player("WR", full_name="Depth WR"),
            "depth_wr2": make_player("WR", full_name="Depth WR 2"),
        }
        for p in players.values():
            p["years_exp"] = 5
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("starter_wr", 500), fc_entry("depth_wr", 100), fc_entry("depth_wr2", 20)]
        )
        replacement_level = {"QB": 0.0, "RB": 0.0, "WR": 50.0, "TE": 0.0}

        pool = trade_module._asset_pool(
            roster, players, fc_by_id, replacement_level, league, {}, EMPTY_PICKS, value_cap=50.0
        )

        assert {c["id"] for c in pool} == {"depth_wr2"}


class TestImproveIncomingOffer:
    """Single-move tweaks to a real proposal, with an accept/counter/reject verdict."""

    LEAGUE = {"roster_positions": ["WR", "BN"]}

    def _base_setup(self):
        your_roster = {"roster_id": 1, "players": ["wr_a", "wr_b"], "taxi": [], "reserve": []}
        partner_roster = {"roster_id": 2, "players": ["target_wr", "other_wr"], "taxi": [], "reserve": []}
        players = {
            "wr_a": make_player("WR", full_name="WR A"),
            "wr_b": make_player("WR", full_name="WR B"),
            "target_wr": make_player("WR", full_name="Target WR"),
            "other_wr": make_player("WR", full_name="Other WR"),
        }
        for p in players.values():
            p["years_exp"] = 5
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("wr_a", 200), fc_entry("wr_b", 100), fc_entry("target_wr", 150), fc_entry("other_wr", 50)]
        )
        replacement_level = {"QB": 0.0, "RB": 0.0, "WR": 0.0, "TE": 0.0}
        return your_roster, partner_roster, players, fc_by_id, replacement_level

    def test_accept_when_baseline_already_good(self, monkeypatch):
        your_roster, partner_roster, players, fc_by_id, replacement_level = self._base_setup()
        script = {
            (1, ("wr_a",), (), ("target_wr",), ()): {"lineup_delta_after_drops": 50.0, "asset_value_delta": 50.0},
            (2, ("target_wr",), (), ("wr_a",), ()): {"asset_value_delta": -50.0},
        }
        monkeypatch.setattr(trade_module, "evaluate_trade", _scripted_evaluate_trade(script))

        result = dc.improve_incoming_offer(
            your_roster, partner_roster, ["wr_a"], [], ["target_wr"], [],
            players, fc_by_id, {}, self.LEAGUE, replacement_level, EMPTY_PICKS,
        )

        assert result["verdict"] == "accept"
        assert result["baseline"]["your_side"]["lineup_delta_after_drops"] == 50.0
        assert result["improvements"] == []

    def test_counter_ranks_swap_and_add_variants_and_rejects_a_lopsided_drop(self, monkeypatch):
        your_roster, partner_roster, players, fc_by_id, replacement_level = self._base_setup()
        script = {
            # Baseline: give wr_a for target_wr - bad for you.
            (1, ("wr_a",), (), ("target_wr",), ()): {"lineup_delta_after_drops": -50.0, "asset_value_delta": -50.0},
            (2, ("target_wr",), (), ("wr_a",), ()): {"asset_value_delta": 50.0},
            # Drop: give nothing for target_wr - great for you, but wildly
            # lopsided against the partner - must be filtered out.
            (1, (), (), ("target_wr",), ()): {"lineup_delta_after_drops": 150.0, "asset_value_delta": 150.0},
            (2, ("target_wr",), (), (), ()): {"asset_value_delta": -150.0},
            # Swap: give wr_b (your sellable depth) instead of wr_a - good
            # for you, acceptable to the partner.
            (1, ("wr_b",), (), ("target_wr",), ()): {"lineup_delta_after_drops": 20.0, "asset_value_delta": 20.0},
            (2, ("target_wr",), (), ("wr_b",), ()): {"asset_value_delta": -20.0},
            # Add: ask for other_wr (partner's sellable depth) too - smaller
            # upside than the swap, still acceptable.
            (1, ("wr_a",), (), ("other_wr", "target_wr"), ()): {"lineup_delta_after_drops": 10.0, "asset_value_delta": 10.0},
            (2, ("other_wr", "target_wr"), (), ("wr_a",), ()): {"asset_value_delta": -10.0},
        }
        monkeypatch.setattr(trade_module, "evaluate_trade", _scripted_evaluate_trade(script))

        result = dc.improve_incoming_offer(
            your_roster, partner_roster, ["wr_a"], [], ["target_wr"], [],
            players, fc_by_id, {}, self.LEAGUE, replacement_level, EMPTY_PICKS,
        )

        assert result["verdict"] == "counter"
        moves = [(imp["move"], imp["side"]) for imp in result["improvements"]]
        assert ("swap", "yours") in moves
        assert ("add", "theirs") in moves
        assert ("drop", "yours") not in moves  # filtered by the partner-tolerance gate
        # Ranked by your_side asset_value_delta descending: swap (20) before add (10).
        assert result["improvements"][0]["move"] == "swap"
        assert result["improvements"][1]["move"] == "add"

    def test_counter_with_a_successful_drop_variant(self, monkeypatch):
        your_roster = {"roster_id": 1, "players": ["wr_a", "wr_c"], "taxi": [], "reserve": []}
        partner_roster = {"roster_id": 2, "players": ["target_wr"], "taxi": [], "reserve": []}
        players = {
            "wr_a": make_player("WR", full_name="WR A"),
            "wr_c": make_player("WR", full_name="WR C"),
            "target_wr": make_player("WR", full_name="Target WR"),
        }
        for p in players.values():
            p["years_exp"] = 5
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("wr_a", 200), fc_entry("wr_c", 30), fc_entry("target_wr", 150)])
        replacement_level = {"QB": 0.0, "RB": 0.0, "WR": 0.0, "TE": 0.0}

        script = {
            # Baseline: partner over-asks for both wr_a and wr_c for target_wr.
            (1, ("wr_a", "wr_c"), (), ("target_wr",), ()): {"lineup_delta_after_drops": -30.0, "asset_value_delta": -30.0},
            (2, ("target_wr",), (), ("wr_a", "wr_c"), ()): {"asset_value_delta": 80.0},
            # Dropping wr_c (giving only wr_a) is a fair, good-for-you deal.
            (1, ("wr_a",), (), ("target_wr",), ()): {"lineup_delta_after_drops": 15.0, "asset_value_delta": 15.0},
            (2, ("target_wr",), (), ("wr_a",), ()): {"asset_value_delta": -15.0},
        }
        monkeypatch.setattr(trade_module, "evaluate_trade", _scripted_evaluate_trade(script))

        result = dc.improve_incoming_offer(
            your_roster, partner_roster, ["wr_a", "wr_c"], [], ["target_wr"], [],
            players, fc_by_id, {}, self.LEAGUE, replacement_level, EMPTY_PICKS,
        )

        assert result["verdict"] == "counter"
        assert any(imp["move"] == "drop" and imp["removed"]["id"] == "wr_c" for imp in result["improvements"])

    def test_reject_when_nothing_clears_the_bar(self, monkeypatch):
        your_roster, partner_roster, players, fc_by_id, replacement_level = self._base_setup()
        script = {
            (1, ("wr_a",), (), ("target_wr",), ()): {"lineup_delta_after_drops": -50.0, "asset_value_delta": -50.0},
            (2, ("target_wr",), (), ("wr_a",), ()): {"asset_value_delta": 50.0},
            # No variant is scripted good - everything else defaults to a
            # neutral (0.0, 0.0), which fails _is_good's strict > 0 bar.
        }
        monkeypatch.setattr(trade_module, "evaluate_trade", _scripted_evaluate_trade(script))

        result = dc.improve_incoming_offer(
            your_roster, partner_roster, ["wr_a"], [], ["target_wr"], [],
            players, fc_by_id, {}, self.LEAGUE, replacement_level, EMPTY_PICKS,
        )

        assert result["verdict"] == "reject"
        assert result["improvements"] == []

    def test_variant_better_than_baseline_but_still_not_good_is_excluded(self, monkeypatch):
        your_roster, partner_roster, players, fc_by_id, replacement_level = self._base_setup()
        script = {
            (1, ("wr_a",), (), ("target_wr",), ()): {"lineup_delta_after_drops": -50.0, "asset_value_delta": -50.0},
            (2, ("target_wr",), (), ("wr_a",), ()): {"asset_value_delta": 50.0},
            # Less bad than baseline but still no lineup gain: not an improvement.
            (1, ("wr_b",), (), ("target_wr",), ()): {"lineup_delta_after_drops": 0.0, "asset_value_delta": -5.0},
            (2, ("target_wr",), (), ("wr_b",), ()): {"asset_value_delta": 5.0},
        }
        monkeypatch.setattr(trade_module, "evaluate_trade", _scripted_evaluate_trade(script))

        result = dc.improve_incoming_offer(
            your_roster, partner_roster, ["wr_a"], [], ["target_wr"], [],
            players, fc_by_id, {}, self.LEAGUE, replacement_level, EMPTY_PICKS,
        )

        assert result["verdict"] == "reject"
        assert result["improvements"] == []

    def test_top_n_caps_the_improvements_list(self, monkeypatch):
        your_roster = {"roster_id": 1, "players": ["wr_a", "wr_b", "wr_c", "wr_d"], "taxi": [], "reserve": []}
        partner_roster = {"roster_id": 2, "players": ["target_wr"], "taxi": [], "reserve": []}
        players = {pid: make_player("WR", full_name=pid) for pid in ["wr_a", "wr_b", "wr_c", "wr_d", "target_wr"]}
        for p in players.values():
            p["years_exp"] = 5
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("wr_a", 300), fc_entry("wr_b", 90), fc_entry("wr_c", 80), fc_entry("wr_d", 70), fc_entry("target_wr", 150)]
        )
        replacement_level = {"QB": 0.0, "RB": 0.0, "WR": 0.0, "TE": 0.0}

        script = {
            (1, ("wr_a",), (), ("target_wr",), ()): {"lineup_delta_after_drops": -50.0, "asset_value_delta": -50.0},
            (2, ("target_wr",), (), ("wr_a",), ()): {"asset_value_delta": 50.0},
        }
        # Partner delta held comfortably within tolerance for all three -
        # only your_side's own value should determine the ranking/cap here.
        for pid, lineup in [("wr_b", 30.0), ("wr_c", 20.0), ("wr_d", 10.0)]:
            script[(1, (pid,), (), ("target_wr",), ())] = {"lineup_delta_after_drops": lineup, "asset_value_delta": lineup}
            script[(2, ("target_wr",), (), (pid,), ())] = {"asset_value_delta": -5.0}
        monkeypatch.setattr(trade_module, "evaluate_trade", _scripted_evaluate_trade(script))

        result = dc.improve_incoming_offer(
            your_roster, partner_roster, ["wr_a"], [], ["target_wr"], [],
            players, fc_by_id, {}, self.LEAGUE, replacement_level, EMPTY_PICKS, top_n=2,
        )

        assert result["verdict"] == "counter"
        assert len(result["improvements"]) == 2
        assert [imp["your_side"]["asset_value_delta"] for imp in result["improvements"]] == [30.0, 20.0]

    def test_heterogeneous_trade_with_a_pick_is_handled(self, monkeypatch):
        your_roster, partner_roster, players, fc_by_id, replacement_level = self._base_setup()
        pick_values = pd.DataFrame([{"pick": "2026 Pick 1.05", "owner": "Partner", "owner_roster_id": 2, "value": 60.0}])
        script = {
            # Baseline: give wr_a for a pick alone - bad.
            (1, ("wr_a",), (), (), ("2026 Pick 1.05",)): {"lineup_delta_after_drops": -80.0, "asset_value_delta": -80.0},
            (2, (), ("2026 Pick 1.05",), ("wr_a",), ()): {"asset_value_delta": 80.0},
            # Add: also ask for other_wr (partner's sellable depth)
            # alongside the pick - good, and still acceptable.
            (1, ("wr_a",), (), ("other_wr",), ("2026 Pick 1.05",)): {"lineup_delta_after_drops": 25.0, "asset_value_delta": 25.0},
            (2, ("other_wr",), ("2026 Pick 1.05",), ("wr_a",), ()): {"asset_value_delta": -25.0},
        }
        monkeypatch.setattr(trade_module, "evaluate_trade", _scripted_evaluate_trade(script))

        result = dc.improve_incoming_offer(
            your_roster, partner_roster, ["wr_a"], [], [], ["2026 Pick 1.05"],
            players, fc_by_id, {}, self.LEAGUE, replacement_level, pick_values,
        )

        assert result["verdict"] == "counter"
        assert any(imp["move"] == "add" and imp["added"]["kind"] == "player" for imp in result["improvements"])

    def test_theirs_side_tolerance_is_anchored_on_outgoing_value_not_the_stale_incoming_ask(self, monkeypatch):
        # A "theirs" variant anchors tolerance on the fixed outgoing value. incoming=300
        # makes the two anchors disagree (45 vs. 25).
        your_roster = {"roster_id": 1, "players": ["wr_a"], "taxi": [], "reserve": []}
        partner_roster = {"roster_id": 2, "players": ["big_target", "cheap_swap"], "taxi": [], "reserve": []}
        players = {
            "wr_a": make_player("WR", full_name="WR A"),
            "big_target": make_player("WR", full_name="Big Target"),
            "cheap_swap": make_player("WR", full_name="Cheap Swap"),
        }
        for p in players.values():
            p["years_exp"] = 5
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("wr_a", 100), fc_entry("big_target", 300), fc_entry("cheap_swap", 130)]
        )
        replacement_level = {"QB": 0.0, "RB": 0.0, "WR": 0.0, "TE": 0.0}

        script = {
            # Baseline: give wr_a (100) for big_target (300) - bad for you,
            # generous to the partner.
            (1, ("wr_a",), (), ("big_target",), ()): {"lineup_delta_after_drops": -10.0, "asset_value_delta": -10.0},
            (2, ("big_target",), (), ("wr_a",), ()): {"asset_value_delta": 200.0},
            # wr_a (100) for cheap_swap (130): delta -30 fails the correct 25 tolerance.
            (1, ("wr_a",), (), ("cheap_swap",), ()): {"lineup_delta_after_drops": 5.0, "asset_value_delta": 5.0},
            (2, ("cheap_swap",), (), ("wr_a",), ()): {"asset_value_delta": -30.0},
        }
        monkeypatch.setattr(trade_module, "evaluate_trade", _scripted_evaluate_trade(script))

        result = dc.improve_incoming_offer(
            your_roster, partner_roster, ["wr_a"], [], ["big_target"], [],
            players, fc_by_id, {}, self.LEAGUE, replacement_level, EMPTY_PICKS,
        )

        assert result["verdict"] == "reject"
        assert result["improvements"] == []
