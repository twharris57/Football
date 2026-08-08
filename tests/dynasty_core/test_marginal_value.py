"""Tests for dynasty_core.marginal_value."""

from __future__ import annotations

import pytest

import dynasty_core as dc
from tests.dynasty_core.helpers import SIMPLE_LEAGUE, fc_entry, make_player


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

    def test_occupied_reserve_slots_count_toward_total_capacity(self):
        # roster_total_capacity() used to omit reserve_slots entirely, so an
        # existing IR occupant's headcount silently ate into active/taxi
        # capacity instead of its own bucket - understating true room and
        # forcing an unnecessary drop even with a genuinely open taxi slot.
        league = {"roster_positions": ["WR"], "settings": {"taxi_slots": 1, "reserve_slots": 1}}
        assert dc.roster_total_capacity(league, reserve_filled=1) == 3  # 1 active + 1 taxi + 1 occupied reserve

        players = {
            "starter_wr": make_player("WR", full_name="Starter WR"),
            "hurt_wr": make_player("WR", full_name="Injured Reserve WR"),
            "new_rookie": make_player("WR", full_name="High Value Rookie"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("starter_wr", 200), fc_entry("hurt_wr", 300), fc_entry("new_rookie", 500)]
        )
        # hurt_wr is on reserve; taxi is genuinely open (0/1 used).
        ineligible_ids = frozenset({"hurt_wr"})

        ranked = dc.rank_by_marginal_value(
            candidate_ids=["new_rookie"],
            hypothetical_ids=["starter_wr", "hurt_wr"],
            players=players,
            fc_by_sleeper_id=fc_by_id,
            byes={},
            league=league,
            top_n=1,
            ineligible_ids=ineligible_ids,
            reserve_filled=1,
        )

        # The rookie fits in the open taxi slot - no drop should be forced,
        # and certainly not the real active starter.
        assert ranked[0]["drop"] is None

    def test_empty_reserve_slots_do_not_count_toward_total_capacity(self):
        # Live-draft bug report: a league with 2 unused reserve_slots (nobody
        # on IR) let the first 2 picks skip a drop entirely, since the old
        # roster_total_capacity() always added the full reserve_slots
        # setting regardless of actual IR occupancy - even though a drafted
        # rookie can never actually be assigned to reserve (that requires a
        # real injury designation). reserve_filled=0 here (its default)
        # should give the same capacity as if reserve_slots didn't exist.
        league = {"roster_positions": ["WR"], "settings": {"taxi_slots": 1, "reserve_slots": 2}}
        assert dc.roster_total_capacity(league) == 2  # 1 active + 1 taxi + 0 occupied reserve

        players = {
            "starter_wr": make_player("WR", full_name="Starter WR"),
            "taxi_wr": make_player("WR", full_name="Taxi WR"),
            "new_rookie": make_player("WR", full_name="High Value Rookie"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("starter_wr", 200), fc_entry("taxi_wr", 100), fc_entry("new_rookie", 500)]
        )
        # Active (1/1) and taxi (1/1) are both already full; nobody is on reserve.
        ineligible_ids = frozenset({"taxi_wr"})

        ranked = dc.rank_by_marginal_value(
            candidate_ids=["new_rookie"],
            hypothetical_ids=["starter_wr", "taxi_wr"],
            players=players,
            fc_by_sleeper_id=fc_by_id,
            byes={},
            league=league,
            top_n=1,
            ineligible_ids=ineligible_ids,
        )

        # No room anywhere the rookie could actually go - a drop must be forced
        # despite 2 nominally "open" reserve_slots that a healthy rookie can't use.
        assert ranked[0]["drop"] is not None
        assert ranked[0]["drop"]["player_id"] == "taxi_wr"

    def test_taxi_eligible_false_does_not_count_open_taxi_slots_as_room(self):
        # SIMPLE_LEAGUE: 7 active + 2 taxi = 9 total capacity with the
        # default taxi_eligible=True. 7 existing players + 1 candidate = 8,
        # which fits under 9 (taxi counted) but exceeds 7 (active-only) -
        # exactly the gap free_agent_board's taxi_eligible=False closes,
        # since Sleeper's real accrued-experience taxi rule isn't modeled
        # and a veteran free agent can't be assumed to fit an open taxi
        # slot the way a rookie safely can.
        players = {f"p{i}": make_player("WR") for i in range(7)}
        players["new_fa"] = make_player("WR")
        fc_values = [fc_entry(f"p{i}", 100 + i) for i in range(7)] + [fc_entry("new_fa", 500)]
        fc_by_id = dc.fc_value_by_sleeper_id(fc_values)
        hypothetical_ids = [f"p{i}" for i in range(7)]

        ranked = dc.rank_by_marginal_value(
            candidate_ids=["new_fa"],
            hypothetical_ids=hypothetical_ids,
            players=players,
            fc_by_sleeper_id=fc_by_id,
            byes={},
            league=SIMPLE_LEAGUE,
            top_n=1,
            taxi_eligible=False,
        )

        assert ranked[0]["drop"] is not None
        # The default (taxi_eligible=True) must be completely unaffected -
        # same call, no drop forced, since 8 <= 9 (active + taxi).
        ranked_default = dc.rank_by_marginal_value(
            candidate_ids=["new_fa"],
            hypothetical_ids=hypothetical_ids,
            players=players,
            fc_by_sleeper_id=fc_by_id,
            byes={},
            league=SIMPLE_LEAGUE,
            top_n=1,
        )
        assert ranked_default[0]["drop"] is None

    def test_taxi_filled_credits_an_existing_taxi_occupant_as_room_already_spent(self):
        # SIMPLE_LEAGUE: 7 active + 2 taxi. Roster already has 6 "regular"
        # players plus 1 existing taxi stash (7 total) - a normal state for
        # this league's rebuild strategy, not an edge case. +1 candidate = 8.
        # Without crediting the existing taxi occupant via taxi_filled,
        # taxi_eligible=False's capacity (7, active-only) would read this as
        # already over before the candidate is even considered - the exact
        # bug found reviewing the trade evaluator. With taxi_filled=1
        # correctly credited, capacity is 8 (7 active + 1 already-spent taxi
        # slot) and no drop should be forced.
        players = {f"p{i}": make_player("WR") for i in range(6)}
        players["taxi_stash"] = make_player("WR", full_name="Taxi Stash")
        players["new_fa"] = make_player("WR")
        fc_values = (
            [fc_entry(f"p{i}", 100 + i) for i in range(6)]
            + [fc_entry("taxi_stash", 50), fc_entry("new_fa", 500)]
        )
        fc_by_id = dc.fc_value_by_sleeper_id(fc_values)
        hypothetical_ids = [f"p{i}" for i in range(6)] + ["taxi_stash"]
        ineligible_ids = frozenset({"taxi_stash"})

        ranked = dc.rank_by_marginal_value(
            candidate_ids=["new_fa"],
            hypothetical_ids=hypothetical_ids,
            players=players,
            fc_by_sleeper_id=fc_by_id,
            byes={},
            league=SIMPLE_LEAGUE,
            top_n=1,
            ineligible_ids=ineligible_ids,
            taxi_eligible=False,
            taxi_filled=1,
        )

        assert ranked[0]["drop"] is None


class TestFreeAgentBoard:
    """free_agent_board should rank available players by marginal value against a roster,
    reusing rank_by_marginal_value exactly like the draft plan does."""

    def test_higher_value_candidate_outranks_lower_value_candidate(self):
        league = {"roster_positions": ["WR", "BN"]}
        roster = {"players": ["starter_wr"], "taxi": [], "reserve": []}
        players = {
            "starter_wr": make_player("WR", full_name="Starter WR"),
            "great_fa": make_player("WR", full_name="Great Free Agent"),
            "meh_fa": make_player("WR", full_name="Meh Free Agent"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("starter_wr", 100), fc_entry("great_fa", 900), fc_entry("meh_fa", 110)]
        )
        pool = {"great_fa": players["great_fa"], "meh_fa": players["meh_fa"]}

        board = dc.free_agent_board(pool, roster, players, fc_by_id, {}, league)

        assert list(board["name"])[0] == "Great Free Agent"

    def test_drop_is_populated_when_roster_is_full(self):
        league = {"roster_positions": ["WR"]}
        roster = {"players": ["low_value_wr"], "taxi": [], "reserve": []}
        players = {
            "low_value_wr": make_player("WR", full_name="Low Value WR"),
            "great_fa": make_player("WR", full_name="Great Free Agent"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("low_value_wr", 50), fc_entry("great_fa", 900)])
        pool = {"great_fa": players["great_fa"]}

        board = dc.free_agent_board(pool, roster, players, fc_by_id, {}, league)

        assert board.iloc[0]["drop_name"] == "Low Value WR"

    def test_existing_taxi_occupant_does_not_force_an_unnecessary_drop(self):
        # A roster with one active starter and one existing taxi stash - the
        # normal state for this league's rebuild strategy, not an edge case.
        # Bug found reviewing the trade evaluator: taxi_eligible=False used
        # to zero taxi capacity entirely, so the existing taxi occupant
        # alone made the roster read as already over capacity, forcing a
        # drop on every single candidate regardless of real open bench room.
        league = {"roster_positions": ["WR", "BN", "BN"], "settings": {"taxi_slots": 2}}
        roster = {"players": ["starter_wr", "taxi_stash"], "taxi": ["taxi_stash"], "reserve": []}
        players = {
            "starter_wr": make_player("WR", full_name="Starter WR"),
            "taxi_stash": make_player("WR", full_name="Taxi Stash"),
            "great_fa": make_player("WR", full_name="Great Free Agent"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("starter_wr", 100), fc_entry("taxi_stash", 50), fc_entry("great_fa", 900)]
        )
        pool = {"great_fa": players["great_fa"]}

        board = dc.free_agent_board(pool, roster, players, fc_by_id, {}, league)

        assert board.iloc[0]["drop_name"] is None


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


class TestRecommendDropExcludedCompetition:
    """exclude_ids protects a player from being *chosen* as the drop, but must not
    remove them from the starter-assignment competition itself - otherwise a
    droppable player can misread as a "starter" just because the excluded
    player(s) who'd actually win that slot were filtered out first."""

    def test_excluded_players_still_count_as_competition_for_starter_status(self):
        # Only one WR slot. "c" and "d" (both 200) are excluded from being
        # the recommended cut, but they still legitimately win the lone WR
        # slot over "b" (100). Before the fix, filtering c/d out before
        # assign_starters ran would let "b" trivially win that slot by
        # default and misread as is_starter: True.
        players = {
            "b": make_player("WR", full_name="B"),
            "c": make_player("WR", full_name="C"),
            "d": make_player("WR", full_name="D"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("b", 100), fc_entry("c", 200), fc_entry("d", 200)])
        league = {"roster_positions": ["WR", "BN"]}

        drop = dc.recommend_drop(["b", "c", "d"], players, fc_by_id, league, exclude_ids=frozenset({"c", "d"}))

        assert drop["player_id"] == "b"
        assert drop["is_starter"] is False


class TestBestPositionRelevantDrop:
    """Unlike recommend_drop's cheap lowest-raw-value heuristic, this should
    (a) only ever consider players who actually share a slot type with the
    candidate, and (b) search for the drop that maximizes the resulting
    marginal value, not just the one with the lowest raw adj_value."""

    def test_only_considers_players_sharing_a_slot_type_with_the_candidate(self):
        # No FLEX/SUPER_FLEX in this league, so a WR candidate should only
        # ever consider other WRs as a drop - never the bench QB, even
        # though it has the lowest raw value on the whole roster.
        league = {"roster_positions": ["QB", "WR", "BN"], "settings": {}}
        players = {
            "starter_qb": make_player("QB", full_name="Starter QB"),
            "starter_wr": make_player("WR", full_name="Starter WR"),
            "bench_qb": make_player("QB", full_name="Bench QB"),
            "bench_wr": make_player("WR", full_name="Bench WR"),
            "new_wr": make_player("WR", full_name="New WR"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [
                fc_entry("starter_qb", 200, position="QB"),
                fc_entry("starter_wr", 300, position="WR"),
                fc_entry("bench_qb", 10, position="QB"),  # global floor - must NOT be picked
                fc_entry("bench_wr", 150, position="WR"),
                fc_entry("new_wr", 500, position="WR"),
            ]
        )
        hypothetical_ids = ["starter_qb", "starter_wr", "bench_qb", "bench_wr"]

        best = dc.best_position_relevant_drop("new_wr", hypothetical_ids, players, fc_by_id, {}, league)

        assert best["player_id"] == "bench_wr"

    def test_picks_the_drop_with_the_greatest_marginal_gain_not_the_lowest_raw_value(self):
        # bench_B has a higher raw value than bench_A, but shares its bye
        # week with both the current starter AND the incoming candidate -
        # keeping it provides zero unique bye coverage. bench_A, despite a
        # lower raw value, is the only player available the one week
        # starter and candidate are both out, so dropping bench_B (and
        # keeping bench_A) yields a strictly better season average - the
        # opposite of what a lowest-raw-value heuristic would choose.
        league = {"roster_positions": ["WR"], "settings": {}}
        players = {
            "starter": make_player("WR", team="T1", full_name="Starter"),
            "bench_a": make_player("WR", team="T3", full_name="Bench A"),
            "bench_b": make_player("WR", team="T4", full_name="Bench B"),
            "candidate": make_player("WR", team="T2", full_name="Candidate"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [
                fc_entry("starter", 200, position="WR"),
                fc_entry("bench_a", 40, position="WR"),
                fc_entry("bench_b", 60, position="WR"),
                fc_entry("candidate", 1000, position="WR"),
            ]
        )
        byes = {"T1": 1, "T2": 1, "T3": 5, "T4": 1}
        hypothetical_ids = ["starter", "bench_a", "bench_b"]

        best = dc.best_position_relevant_drop("candidate", hypothetical_ids, players, fc_by_id, byes, league)

        assert best["player_id"] == "bench_b"

    def test_superflex_league_still_finds_the_correct_cross_position_drop(self):
        # RT-17: with a SUPER_FLEX slot (this league, always),
        # SUPERFLEX_ELIGIBLE_POSITIONS is all four fantasy positions, so the
        # "restrict to a shared slot type" narrowing is a no-op - a WR
        # candidate's search pool includes a bench QB too, not just other
        # WRs. Confirmed correctness (not just a no-op) rests on the real
        # simulation: same bye-overlap trick as the test above (a lower-raw-
        # value bench player who uniquely covers a week the higher-value one
        # doesn't), but across positions - bench_qb (not another WR) is the
        # one worth keeping. starter_flex fills the SUPER_FLEX slot on its
        # own, ahead of both bench_qb/bench_wr, so both genuinely start on
        # the bench before the candidate is even considered - otherwise
        # bench_wr (60 > 40) would already be a real starter itself and
        # never enter the drop search in the first place.
        league = {"roster_positions": ["WR", "SUPER_FLEX"], "settings": {}}
        players = {
            "starter_wr": make_player("WR", team="T1", full_name="Starter WR"),
            "starter_flex": make_player("RB", team="T5", full_name="Starter Flex"),
            "bench_qb": make_player("QB", team="T3", full_name="Bench QB"),
            "bench_wr": make_player("WR", team="T4", full_name="Bench WR"),
            "candidate": make_player("WR", team="T2", full_name="Candidate"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [
                fc_entry("starter_wr", 200, position="WR"),
                fc_entry("starter_flex", 150, position="RB"),
                fc_entry("bench_qb", 40, position="QB"),  # lower raw value...
                fc_entry("bench_wr", 60, position="WR"),  # ...but this outranks it if compared naively
                fc_entry("candidate", 1000, position="WR"),
            ]
        )
        # T1/T2/T4/T5 share bye week 1 (bench_wr provides zero unique
        # coverage that week - it's out right alongside everyone else); T3
        # (bench_qb) is out a different week (5), when the others are
        # already covering both slots anyway. Keeping bench_qb strictly
        # beats keeping bench_wr on season-average value.
        byes = {"T1": 1, "T2": 1, "T3": 5, "T4": 1, "T5": 1}
        hypothetical_ids = ["starter_wr", "starter_flex", "bench_qb", "bench_wr"]

        best = dc.best_position_relevant_drop("candidate", hypothetical_ids, players, fc_by_id, byes, league)

        assert best["player_id"] == "bench_wr"


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
