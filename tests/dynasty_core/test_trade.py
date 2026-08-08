"""Tests for dynasty_core.trade."""

from __future__ import annotations

import math

import pandas as pd
import pytest

import dynasty_core as dc
from tests.dynasty_core.helpers import EMPTY_PICKS, fc_entry, make_player


class TestSellablePlayers:
    """Sellable candidates are a surplus position's own bench depth beyond
    its starters, not the starters themselves and not rookies - and only
    if dropping them wouldn't open a weekly-depth hole."""

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

        # wr1 is the position's 1 starter (excluded even though it's the
        # most valuable) - wr3 is depth but a rookie (excluded) - only wr2
        # is real, sellable veteran depth.
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
    """evaluate_trade should compute an independent lineup-value read and asset-value
    read for one side of an arbitrary multi-asset (players + picks) trade, and be
    reusable as-is for the other side of the identical trade with roster/assets swapped."""

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
        # Same setup as the over-capacity test above: roster ["a", "b"]
        # (both 100), receiving ["c", "d"] (both 200) for "a" - one over.
        # The only eligible drop is "b" (the sole pre-existing player left
        # after excluding the newly-incoming c/d from consideration). Both
        # b's value and the real post-trade competition (c and d both
        # outscore b for the 2 slots) agree b was never starting anyway, so
        # lineup_delta_after_drops equals the raw lineup_delta here -
        # covered separately below where they *do* diverge.
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
        # Only 1 roster slot, no bench. Roster keeps "a" (value 100);
        # receives "c" (value 50, lower) with nothing given up - 1 over
        # capacity. The only player eligible to be the forced cut is "a"
        # (c is protected as incoming), even though "a" is worth more and
        # was the one actually winning the real slot in the raw after-trade
        # comparison - a real cost the raw lineup_delta alone hides.
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
        # Once forced to cut someone and "a" is the only eligible option,
        # the real post-cut lineup is just "c" (50) - a real loss the raw
        # number above doesn't capture.
        assert result["lineup_delta_after_drops"] == pytest.approx(-50.0)

    def test_recommends_multiple_drops_when_over_capacity_by_more_than_one(self):
        # Capacity 2; roster starts with 3 pre-existing players (a=100,
        # b=90, x=80) plus 1 incoming (c=500) - roster_after size 4, 2 over.
        # Both drops must come from the pre-existing players, lowest value
        # first, never c (the just-acquired player).
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
        # A roster with one active starter and one existing taxi stash -
        # normal for this league's rebuild strategy. Bug found reviewing
        # this feature: taxi_eligible=False used to zero taxi capacity
        # entirely, so the existing taxi occupant alone made a plain 1-for-1
        # swap (no net roster-size change) read as already over capacity.
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
        # reserve_filled/taxi_filled must reflect the roster AFTER the trade,
        # not before - trading away a player currently on IR genuinely frees
        # that slot, so it must not still count as spoken-for capacity.
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

        # Trading away the IR player itself for 2 incoming: roster_size_after
        # = 1 (active_wr) + 2 (incoming) = 3. Capacity = 1 active slot + 0
        # reserve_filled (the only IR occupant is the one being traded away)
        # = 1 - so this SHOULD read over capacity (3 > 1), but reserve_filled
        # must be 0, not 1, since ir_wr is leaving.
        result = dc.evaluate_trade(
            roster, ["ir_wr"], ["incoming_a", "incoming_b"], players, fc_by_id, {}, league
        )

        assert result["capacity"] == 1

    def test_the_other_side_of_the_same_trade_mirrors_asset_value_delta(self):
        # Calling evaluate_trade again with the partner's own roster and the
        # two asset lists swapped is the whole "two-sided" evaluation - not
        # a second implementation, so the asset-value deltas must be exact
        # negatives of each other for the identical trade.
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
    """RT-18: evaluate_trade() should surface non-obvious value beyond the lineup/asset
    deltas - a bye-week gap opened or closed, a handcuff to a kept RB, a buried bench
    player given up or an instant starter received, and a traded pick's rank in its
    own class - each composed from an existing primitive, not a new signal."""

    def test_omitting_handcuffs_and_pick_context_means_no_error_and_no_such_callouts(self):
        # Omitting handcuffs/pick names/pick_value_table (the pre-RT-18 call
        # shape, still used by every other existing test in this file) must
        # not error - it just means those two specific callouts can't fire.
        # (The bye-gap/buried-bench/instant-starter callouts don't depend on
        # this optional context, so they're exercised in their own tests
        # below rather than asserted away here.)
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
        # pick_trade_values() names next-season picks "{season} {round}st/nd/..."
        # (e.g. "2027 1st") since there's no real draft object yet to assign
        # a slot - no " Pick " substring, unlike this season's slot-specific
        # "2026 Pick R.SS" names. Splitting on " Pick " to derive "season"
        # would leave a next-season pick's season as its own full name,
        # stranding it alone in a one-pick class that always ranks #1 with a
        # garbled season label - this locks in the leading-year-based fix.
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
        # A pick name with nothing matching the leading-year pattern (never
        # a real pick_trade_values() output, but shouldn't be able to crash
        # this) must fall back gracefully - its own name as an isolated
        # "season" - rather than leaving a NaN season that breaks the
        # int-cast rank column for every other pick's callout too.
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
    """find_trade_offers should answer 'is this target worth pursuing' by direct reuse of
    evaluate_trade(), then search the caller's own sellable players/picks for offers a
    partner would plausibly accept (their own asset_value_delta staying within tolerance
    of the target's value) - ranked best-for-the-caller first, need-matches preferred among
    ties, never forcing a suggestion when nothing clears the partner's bar."""

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

    def test_lopsided_combo_is_filtered_even_when_cheap_for_you(self):
        # cheap_wr (120) for target_wr (200) looks great for you in
        # isolation (evaluate_trade's own asset_value_delta is positive),
        # but it lowballs the partner well past tolerance - it must not
        # surface as a suggested offer despite being attractive one-sided.
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
        # Two equally-valued single-asset combos (a WR and an RB, both 100)
        # against a 100-value target - identical asset_value_delta on your
        # side. The partner has real WR depth but only one, old RB - RB is
        # their flagged need, WR isn't - so the RB combo should rank first
        # even though the two are otherwise tied.
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
        # 30 owned picks, no sellable players at all - the pool must still
        # cap to TRADE_OFFER_POOL_CAP before combos are generated, so the
        # combo count stays fixed regardless of how many candidates exist.
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
        # 15 expensive picks (500 each) plus 5 cheap picks (20-28) that
        # actually match a 30-value target. Capping the pool by raw
        # descending value alone (the old behavior) would keep only the 15
        # expensive picks - none of which could ever land in-band, since
        # adding more assets only raises combo_value further - starving the
        # search of the genuinely matching cheap ones entirely. The pre-cap
        # prune (drop anything already over TRADE_OFFER_PREFILTER_HIGH of
        # the target's value) must remove the out-of-band picks first so
        # the cheap ones survive into the capped pool.
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
        # unranked_target has no FantasyCalc entry at all - a real data gap,
        # not a genuinely-worthless player. The search must not treat that
        # as "worth $0" and go looking for a plausible offer against a
        # fabricated baseline (which would make literally any throwaway
        # asset look like a clearing offer).
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
        # A pick present in the table but with an unmatched FantasyCalc
        # name (pick_trade_values()'s own documented naming-mismatch gap)
        # carries a real NaN, not a missing key - `NaN or 0.0` would
        # otherwise leave target_value as NaN and poison every comparison
        # built from it (tolerance, the acceptance gate) without raising.
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
        # unmatched_wr has no FantasyCalc entry, so sellable_players()'s
        # adj_value for it comes back as real NaN once its row goes through
        # a DataFrame (not a None a bare `or 0.0` would catch - NaN is
        # truthy in Python). The pool must fall back to 0.0 for it, like
        # every other possibly-missing-value spot in this codebase, rather
        # than letting a NaN combo value slip into a displayed offer.
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
        # RT-18: find_trade_offers() should thread its own handcuffs/
        # pick_value_table into evaluate_trade()'s callouts, not just use
        # them for the offer search itself.
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
