"""Tests for dynasty_core.py's ranking and lineup logic.

Everything here uses synthetic players/league/values, never a real Sleeper
or FantasyCalc call — per testing.md ("mock only external services you do
not control"), but these are pure functions over plain data structures, so
there's nothing to mock in the first place, just data to construct.
`TestGatherStateConnectivityErrors` is the exception: it monkeypatches
sleeper_api/fantasycalc_api directly, which testing.md's "mock only
external services you do not control" explicitly allows.
"""

from __future__ import annotations

import pytest
import requests

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


class TestTeamRosterAnalysis:
    """team_roster_analysis should bundle every per-roster view for ANY roster,
    not just the user's own - the basis for the Your Roster tab's team selector."""

    def test_bundles_every_view_for_an_arbitrary_roster(self):
        league = {"roster_positions": ["QB", "WR", "BN"], "settings": {"taxi_slots": 1, "reserve_slots": 1}}
        players = {
            "qb1": make_player("QB", team="AAA", full_name="QB One"),
            "wr1": make_player("WR", team="AAA", full_name="WR One"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("qb1", 100, position="QB"), fc_entry("wr1", 200, position="WR")]
        )
        roster = {"players": ["qb1", "wr1"], "taxi": [], "reserve": []}

        analysis = dc.team_roster_analysis(roster, players, fc_by_id, {}, league, {})

        assert set(analysis.keys()) == {
            "roster_needs",
            "need_positions",
            "roster_capacity",
            "roster_value",
            "roster_bye_conflicts",
            "roster_weekly_gaps",
            "roster_handcuffs",
            "lineup_starters",
            "lineup_bench",
            "lineup_taxi",
            "lineup_ir",
        }
        assert analysis["roster_capacity"]["active_filled"] == 2
        assert set(analysis["lineup_starters"]["name"]) == {"QB One", "WR One"}


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


class TestPlayerStatusDetails:
    """(icon, description) pairs for a player's situation - a player can have more than one."""

    def test_rookie_with_no_years_exp_is_flagged(self):
        info = {"years_exp": 0}
        assert dc.player_status_details("p1", info, taxi_ids=set(), reserve_ids=set()) == [
            ("🆕", "Rookie (no NFL experience yet)")
        ]

    def test_established_healthy_active_player_has_no_flags(self):
        info = {"years_exp": 5, "injury_status": None}
        assert dc.player_status_details("p1", info, taxi_ids=set(), reserve_ids=set()) == []

    def test_injury_status_uses_the_raw_word_for_a_clear_status(self):
        info = {"years_exp": 5, "injury_status": "Questionable"}
        assert dc.player_status_details("p1", info, taxi_ids=set(), reserve_ids=set()) == [("🏥", "Questionable")]

    def test_injury_status_expands_a_cryptic_abbreviation(self):
        info = {"years_exp": 5, "injury_status": "PUP"}
        assert dc.player_status_details("p1", info, taxi_ids=set(), reserve_ids=set()) == [
            ("🏥", "Physically Unable to Perform")
        ]

    def test_taxi_and_reserve_are_flagged_independently_of_roster_data(self):
        info = {"years_exp": 5}
        assert dc.player_status_details("p1", info, taxi_ids={"p1"}, reserve_ids=set()) == [("🌱", "Taxi squad")]
        assert dc.player_status_details("p1", info, taxi_ids=set(), reserve_ids={"p1"}) == [
            ("🩹", "IR / Reserve")
        ]

    def test_multiple_flags_combine(self):
        # A rookie stashed on taxi who's also currently questionable.
        info = {"years_exp": 0, "injury_status": "Questionable"}
        assert dc.player_status_details("p1", info, taxi_ids={"p1"}, reserve_ids=set()) == [
            ("🆕", "Rookie (no NFL experience yet)"),
            ("🏥", "Questionable"),
            ("🌱", "Taxi squad"),
        ]


class TestPlayerStatusFlags:
    """Compact icon-only summary of player_status_details, for plain-text display (the CLI)."""

    def test_icons_only_no_descriptions(self):
        info = {"years_exp": 0, "injury_status": "Questionable"}
        assert dc.player_status_flags("p1", info, taxi_ids={"p1"}, reserve_ids=set()) == "🆕 🏥 🌱"

    def test_no_flags_is_an_empty_string(self):
        info = {"years_exp": 5, "injury_status": None}
        assert dc.player_status_flags("p1", info, taxi_ids=set(), reserve_ids=set()) == ""


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

    def test_rookie_bucket_preferred_over_position_average(self):
        multipliers = {"per_player": {}, "rookie_bucket": {"qb1": 1.3}, "position_average": {"QB": 1.5}}

        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("qb1", 100, position="QB")], multipliers)

        assert fc_by_id["qb1"]["adj_value"] == pytest.approx(130.0)

    def test_personalized_multiplier_preferred_over_rookie_bucket(self):
        multipliers = {"per_player": {"qb1": 2.0}, "rookie_bucket": {"qb1": 1.3}, "position_average": {"QB": 1.5}}

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

    def test_all_candidates_by_pick_includes_every_evaluated_option(self):
        # rank_by_marginal_value already scores every candidate before
        # picking a winner - all_candidates_by_pick should expose all of
        # them (for a UI lookup), not just the one recommended pick.
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
        ownership = [dc.DraftPickSlot(round=1, overall_pick=1, original_roster_id=1, owner_roster_id=1)]
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

        candidates = plan["all_candidates_by_pick"][1]
        assert set(candidates["name"]) == {"Good QB", "Good WR"}
        # Both evaluated candidates are present and correctly ordered by
        # marginal value, not just the one actually recommended.
        assert candidates.iloc[0]["name"] == "Good QB"
        assert candidates.iloc[0]["marginal_value"] > candidates.iloc[1]["marginal_value"]


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
