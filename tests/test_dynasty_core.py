"""Tests for dynasty_core.py's ranking and lineup logic.

Everything here uses synthetic players/league/values, never a real Sleeper
or FantasyCalc call — per testing.md ("mock only external services you do
not control"), but these are pure functions over plain data structures, so
there's nothing to mock in the first place, just data to construct.
"""

from __future__ import annotations

import pytest

import dynasty_core as dc

SIMPLE_LEAGUE = {
    "roster_positions": ["QB", "RB", "WR", "FLEX", "SUPER_FLEX", "BN", "BN"],
    "settings": {"taxi_slots": 2},
}


def make_player(position: str, team: str = "AAA", full_name: str | None = None) -> dict:
    return {"position": position, "team": team, "full_name": full_name or f"{position}-{team}"}


def fc_entry(sleeper_id: str, value: float, tier: int = 1, position: str | None = None) -> dict:
    return {"player": {"sleeperId": sleeper_id, "position": position}, "value": value, "maybeTier": tier}


class TestComputePickOwnership:
    """The overall-pick math assumes a linear draft; a different type must fail loudly, not silently."""

    def test_raises_for_a_non_linear_draft_type(self):
        draft = {"type": "snake", "settings": {"teams": 2, "rounds": 1}, "slot_to_roster_id": {"1": 1, "2": 2}}

        with pytest.raises(ValueError, match="linear"):
            dc.compute_pick_ownership(draft, [], "2026")

    def test_linear_draft_keeps_the_same_slot_order_every_round(self):
        draft = {"type": "linear", "settings": {"teams": 2, "rounds": 2}, "slot_to_roster_id": {"1": 1, "2": 2}}

        picks = dc.compute_pick_ownership(draft, [], "2026")

        assert [p.original_roster_id for p in picks] == [1, 2, 1, 2]


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


class TestCapacityAwareDrop:
    """rank_by_marginal_value should only force a drop when the roster is genuinely full.

    Regression coverage for the pre-draft-review bug: recommend_drop() used
    to be called unconditionally for every candidate, even with open
    active/taxi capacity, understating marginal value and risking an
    unnecessary cut.
    """

    def test_no_drop_forced_when_roster_has_open_capacity(self):
        # SIMPLE_LEAGUE's total capacity is 7 roster_positions + 2 taxi = 9;
        # 2 existing players + 1 candidate is well under that.
        players = {"qb1": make_player("QB"), "rb1": make_player("RB"), "wr1": make_player("WR")}
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("qb1", 100), fc_entry("rb1", 100), fc_entry("wr1", 50)])

        ranked = dc.rank_by_marginal_value(
            candidate_ids=["wr1"],
            hypothetical_ids=["qb1", "rb1"],
            players=players,
            fc_by_sleeper_id=fc_by_id,
            byes={},
            league=SIMPLE_LEAGUE,
            top_n=1,
        )

        assert ranked[0]["drop"] is None

    def test_drop_forced_when_roster_is_at_total_capacity(self):
        # Exactly 9 existing players (SIMPLE_LEAGUE's total capacity) + 1
        # candidate must force a drop - there's nowhere left to put them.
        players = {f"p{i}": make_player("WR") for i in range(9)}
        players["new"] = make_player("WR")
        fc_values = [fc_entry(f"p{i}", 100 + i) for i in range(9)] + [fc_entry("new", 500)]
        fc_by_id = dc.fc_value_by_sleeper_id(fc_values)

        ranked = dc.rank_by_marginal_value(
            candidate_ids=["new"],
            hypothetical_ids=list(players.keys())[:9],
            players=players,
            fc_by_sleeper_id=fc_by_id,
            byes={},
            league=SIMPLE_LEAGUE,
            top_n=1,
        )

        assert ranked[0]["drop"] is not None
        # Lowest-value player (p0) should be the one dropped.
        assert ranked[0]["drop"]["player_id"] == "p0"


class TestRecommendDropIneligibility:
    """A taxi/IR player must never be misclassified as a "starter", even if its
    value alone would otherwise win a starting slot - Sleeper doesn't allow
    starting them, so they can't be wrongly protected from the drop pool."""

    def test_high_value_taxi_player_is_never_marked_a_starter(self):
        players = {"starter": make_player("WR"), "taxi_wr": make_player("WR")}
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("starter", 50), fc_entry("taxi_wr", 500)])
        league = {"roster_positions": ["WR"]}

        drop = dc.recommend_drop(
            ["starter", "taxi_wr"], players, fc_by_id, league, ineligible_ids=frozenset({"taxi_wr"})
        )

        # Without the fix, taxi_wr's 500 value would win the WR slot and get
        # misclassified as a starter, leaving "starter" (50) as the only
        # bench candidate - recommending a cut to the real active starter
        # while the taxi player sat falsely "protected".
        assert drop["player_id"] == "taxi_wr"
        assert drop["is_starter"] is False


class TestPlayerStatusFlags:
    """Compact icon summary of a player's situation - a player can show more than one flag."""

    def test_rookie_with_no_years_exp_is_flagged(self):
        info = {"years_exp": 0}
        assert dc.player_status_flags("p1", info, taxi_ids=set(), reserve_ids=set()) == "🆕"

    def test_established_healthy_active_player_has_no_flags(self):
        info = {"years_exp": 5, "injury_status": None}
        assert dc.player_status_flags("p1", info, taxi_ids=set(), reserve_ids=set()) == ""

    def test_injury_status_shown_as_icon_plus_first_letter(self):
        info = {"years_exp": 5, "injury_status": "Questionable"}
        assert dc.player_status_flags("p1", info, taxi_ids=set(), reserve_ids=set()) == "🏥Q"

    def test_taxi_and_reserve_are_flagged_independently_of_roster_data(self):
        info = {"years_exp": 5}
        assert dc.player_status_flags("p1", info, taxi_ids={"p1"}, reserve_ids=set()) == "🌱"
        assert dc.player_status_flags("p1", info, taxi_ids=set(), reserve_ids={"p1"}) == "🩹"

    def test_multiple_flags_combine(self):
        # A rookie stashed on taxi who's also currently questionable.
        info = {"years_exp": 0, "injury_status": "Questionable"}
        assert dc.player_status_flags("p1", info, taxi_ids={"p1"}, reserve_ids=set()) == "🆕 🏥Q 🌱"


class TestSeasonAverageStarterValue:
    """Bye weeks should reduce the season average proportionally, not distort it."""

    def test_bye_week_zeroes_out_that_weeks_contribution(self):
        players = {"wr1": make_player("WR", team="AAA")}
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("wr1", 100)])
        byes = {"AAA": 5}
        league = {"roster_positions": ["WR"], "settings": {"taxi_slots": 0}}

        avg = dc.season_average_starter_value(["wr1"], players, fc_by_id, byes, league)

        # Contributes 100 in 17 of 18 weeks, 0 in the bye week.
        assert avg == pytest.approx((100 * 17) / 18)

    def test_ineligible_players_never_win_a_starting_slot(self):
        # A high-value taxi player must not be assignable as a "starter" -
        # Sleeper doesn't allow starting a taxi/IR player.
        players = {
            "starter": make_player("WR", team="AAA"),
            "taxi_wr": make_player("WR", team="BBB"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("starter", 50), fc_entry("taxi_wr", 500)])
        league = {"roster_positions": ["WR"]}

        avg = dc.season_average_starter_value(
            ["starter", "taxi_wr"], players, fc_by_id, {}, league, ineligible_ids=frozenset({"taxi_wr"})
        )

        # If taxi_wr were eligible it would win every week at 500; it must not.
        assert avg == pytest.approx(50.0)


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


class TestPersonalizedMultipliers:
    """fc_value_by_sleeper_id should prefer a per-player multiplier (see player_scoring.py)
    over the position average, and fall back sensibly when one isn't available."""

    def test_personalized_multiplier_preferred_over_position_average(self):
        multipliers = {"per_player": {"qb1": 2.0}, "position_average": {"QB": 1.5}}

        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("qb1", 100, position="QB")], multipliers)

        assert fc_by_id["qb1"]["adj_value"] == pytest.approx(200.0)

    def test_falls_back_to_position_average_when_no_personalized_entry(self):
        multipliers = {"per_player": {}, "position_average": {"QB": 1.5}}

        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("qb1", 100, position="QB")], multipliers)

        assert fc_by_id["qb1"]["adj_value"] == pytest.approx(150.0)

    def test_falls_back_to_hardcoded_constant_when_no_multipliers_available(self):
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("qb1", 100, position="QB")])

        assert fc_by_id["qb1"]["adj_value"] == pytest.approx(100 * dc.POSITION_VALUE_MULTIPLIER["QB"])


class TestMultiRoundPlan:
    """End-to-end: multi_round_plan should fill a true positional need before a
    same-position depth upgrade, and carry each round's pick into the next."""

    def test_fills_empty_starting_slot_before_a_same_position_upgrade(self):
        league = {"roster_positions": ["QB", "WR", "BN"], "settings": {"taxi_slots": 0}}
        players = {
            "old_wr": make_player("WR", full_name="Old WR"),
            "good_qb": make_player("QB", full_name="Good QB"),
            "good_wr": make_player("WR", full_name="Good WR"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [
                fc_entry("old_wr", 50, position="WR"),
                fc_entry("good_qb", 300, position="QB"),
                fc_entry("good_wr", 100, position="WR"),
            ]
        )
        user_roster = {"players": ["old_wr"], "taxi": [], "reserve": []}
        ownership = [
            dc.DraftPickSlot(round=1, overall_pick=1, original_roster_id=1, owner_roster_id=1),
            dc.DraftPickSlot(round=2, overall_pick=2, original_roster_id=1, owner_roster_id=1),
        ]
        available = {"good_qb": players["good_qb"], "good_wr": players["good_wr"]}

        plan = dc.multi_round_plan(
            ownership=ownership,
            user_roster_id=1,
            current_pick_no=1,
            available=available,
            players=players,
            fc_by_sleeper_id=fc_by_id,
            user_roster=user_roster,
            league=league,
            byes={},
            handcuffs={},
            real_picks_by_overall={},
        )

        rounds = plan["rounds"]
        # Round 1 fills the completely-empty QB slot (marginal +300) rather
        # than a modest WR depth upgrade (marginal +50 - old_wr stays
        # started either way, just at a higher value).
        assert rounds.iloc[0]["pick_name"] == "Good QB"
        assert rounds.iloc[0]["status"] == "upcoming"
        # Round 2 correctly builds on round 1's pick, taking the only
        # remaining candidate.
        assert rounds.iloc[1]["pick_name"] == "Good WR"
        # Exactly at capacity (3 players, 3 slots, no taxi) - never over it,
        # so no drop should have been forced in either round.
        assert rounds["drop_name"].isna().all()
        # Adding a QB can only improve the roster's weekly gaps, never worsen
        # them - no new/worse gap alerts expected.
        assert plan["weekly_gap_alerts"].empty
