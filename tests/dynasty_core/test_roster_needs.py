"""Tests for dynasty_core.roster_needs."""

from __future__ import annotations

import pandas as pd
import pytest

import dynasty_core as dc
from tests.dynasty_core.helpers import fc_entry, make_player


class TestPositionStarterDemand:
    """SUPER_FLEX demand should count as extra QB demand specifically - the
    confirmed fix for the review-flagged QB VOR undercount - not applied to
    any other position (FLEX-for-RB/WR/TE stays a deliberately unmodeled gap)."""

    def test_super_flex_adds_to_qb_demand_only(self):
        roster_positions = ["QB", "SUPER_FLEX", "WR", "BN"]

        assert dc._position_starter_demand("QB", roster_positions) == 2  # 1 dedicated + 1 SUPER_FLEX
        assert dc._position_starter_demand("WR", roster_positions) == 1  # unaffected

    def test_floors_at_one_even_with_zero_dedicated_slots(self):
        assert dc._position_starter_demand("TE", ["QB", "WR"]) == 1


class TestPositionReplacementLevels:
    """Replacement level should be an external, league-wide baseline - the Nth-best
    rostered player at a position, N = starter demand * number of teams - not
    anything relative to a single roster."""

    def test_replacement_level_is_the_nth_best_player_leaguewide(self):
        # 1 dedicated WR slot * 2 teams = rank 2 - the 2nd-best WR leaguewide.
        league_roster_positions = ["WR", "BN"]
        players = {
            "wr_a1": make_player("WR", full_name="A1"),
            "wr_a2": make_player("WR", full_name="A2"),
            "wr_b1": make_player("WR", full_name="B1"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [
                fc_entry("wr_a1", 300, position="WR"),
                fc_entry("wr_a2", 100, position="WR"),
                fc_entry("wr_b1", 200, position="WR"),
            ]
        )
        rosters = [{"players": ["wr_a1", "wr_a2"]}, {"players": ["wr_b1"]}]

        levels = dc.position_replacement_levels(rosters, players, fc_by_id, league_roster_positions)

        # Sorted WR pool: [300, 200, 100] - rank 2 is 200.
        assert levels["WR"] == pytest.approx(200.0)

    def test_position_with_no_rostered_players_is_zero(self):
        levels = dc.position_replacement_levels([{"players": []}], {}, {}, ["QB", "BN"])

        assert levels["TE"] == 0.0

    def test_super_flex_deepens_qb_replacement_rank(self):
        # 1 dedicated QB slot + 1 SUPER_FLEX * 2 teams = rank 4, not rank 2 -
        # the review-flagged bug this test guards against regressing.
        # position deliberately omitted from fc_entry - passing "QB" would
        # trigger the real POSITION_VALUE_MULTIPLIER fallback (1.175x) and
        # break this test's hand-computed values below.
        league_roster_positions = ["QB", "SUPER_FLEX", "BN"]
        players = {f"qb{i}": make_player("QB", full_name=f"QB{i}") for i in range(5)}
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry(f"qb{i}", v) for i, v in enumerate([500, 400, 300, 200, 100])]
        )
        rosters = [{"players": ["qb0", "qb1", "qb2"]}, {"players": ["qb3", "qb4"]}]

        levels = dc.position_replacement_levels(rosters, players, fc_by_id, league_roster_positions)

        # Sorted QB pool: [500, 400, 300, 200, 100] - rank 4 is 200, not rank 2's 400.
        assert levels["QB"] == pytest.approx(200.0)


class TestPositionalStrengthSummary:
    """vor/weak should reflect the roster's own top starter-count players at a
    position against the external replacement_level baseline - not raw depth."""

    def test_positive_vor_when_starters_clear_replacement_level(self):
        league_roster_positions = ["WR", "BN"]
        players = {
            "wr1": make_player("WR", full_name="WR One"),
            "wr2": make_player("WR", full_name="WR Two"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("wr1", 300, position="WR"), fc_entry("wr2", 100, position="WR")]
        )
        roster = {"players": ["wr1", "wr2"]}

        summary = dc.positional_strength_summary(roster, players, fc_by_id, {"WR": 200.0}, league_roster_positions)

        # Only the top 1 (dedicated WR slot count) counts toward starter_value: 300.
        assert summary.loc["WR", "starter_value"] == pytest.approx(300.0)
        assert summary.loc["WR", "vor"] == pytest.approx(100.0)  # 300 - 200
        assert not summary.loc["WR", "weak"]

    def test_weak_when_starters_dont_clear_replacement_level(self):
        league_roster_positions = ["WR", "BN"]
        players = {"wr1": make_player("WR", full_name="WR One")}
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("wr1", 50, position="WR")])
        roster = {"players": ["wr1"]}

        summary = dc.positional_strength_summary(roster, players, fc_by_id, {"WR": 200.0}, league_roster_positions)

        assert summary.loc["WR", "vor"] == pytest.approx(-150.0)
        assert summary.loc["WR", "weak"]

    def test_super_flex_counts_a_second_qb_toward_starter_value(self):
        # 1 dedicated QB + 1 SUPER_FLEX = top 2 QBs count toward starter_value,
        # not just the top 1 - the review-flagged bug this test guards against.
        league_roster_positions = ["QB", "SUPER_FLEX", "BN"]
        players = {
            "qb1": make_player("QB", full_name="QB One"),
            "qb2": make_player("QB", full_name="QB Two"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("qb1", 300), fc_entry("qb2", 100)])
        roster = {"players": ["qb1", "qb2"]}

        summary = dc.positional_strength_summary(roster, players, fc_by_id, {"QB": 50.0}, league_roster_positions)

        # Both QBs count: 300 + 100 = 400, not just the top one (300).
        assert summary.loc["QB", "starter_value"] == pytest.approx(400.0)
        assert summary.loc["QB", "vor"] == pytest.approx(300.0)  # 400 - (50 * 2)


class TestNeedFromPhase:
    """The rebuild-phase-aware "need" switch: young-core count while
    rebuilding, the VOR-based "weak" read otherwise - binary, not a
    three-way blend across the three phase labels."""

    def test_rebuilding_uses_young_core_threshold(self):
        young_core = pd.Series([0, 3], index=["QB", "WR"])
        weak = pd.Series([True, False], index=["QB", "WR"])

        result = dc._need_from_phase(young_core, weak, "rebuilding")

        # YOUNG_CORE_NEED_THRESHOLD is 2 - 0 < 2 is a need, 3 < 2 is not.
        assert list(result) == [True, False]

    def test_treading_water_uses_weak_not_young_core(self):
        young_core = pd.Series([0, 3], index=["QB", "WR"])
        weak = pd.Series([False, True], index=["QB", "WR"])

        result = dc._need_from_phase(young_core, weak, "treading_water")

        assert list(result) == [False, True]

    def test_contending_uses_weak_not_young_core(self):
        young_core = pd.Series([0], index=["QB"])
        weak = pd.Series([True], index=["QB"])

        result = dc._need_from_phase(young_core, weak, "contending")

        assert list(result) == [True]


class TestPhaseAwareNeedPositions:
    """phase_aware_need_positions should switch which signal drives "need"
    exactly like _need_from_phase, for a caller with no pre-joined table."""

    def test_rebuilding_and_contending_can_disagree_on_the_same_roster(self):
        league_roster_positions = ["WR", "BN"]
        players = {
            "wr1": {"position": "WR", "team": "AAA", "full_name": "WR One", "age": 22, "years_exp": 1},
            "wr2": {"position": "WR", "team": "AAA", "full_name": "WR Two", "age": 23, "years_exp": 1},
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("wr1", 50, position="WR"), fc_entry("wr2", 30, position="WR")]
        )
        roster = {"players": ["wr1", "wr2"]}
        # Both WRs are far below this - the position is "weak", even though
        # it's not short on young bodies (2 players <= YOUNG_CORE_MAX_YOE
        # already meets YOUNG_CORE_NEED_THRESHOLD).
        replacement_level = {"WR": 200.0}

        rebuilding_needs = dc.phase_aware_need_positions(
            roster, players, fc_by_id, replacement_level, league_roster_positions, "rebuilding"
        )
        contending_needs = dc.phase_aware_need_positions(
            roster, players, fc_by_id, replacement_level, league_roster_positions, "contending"
        )

        assert "WR" not in rebuilding_needs
        assert "WR" in contending_needs

    def test_empty_roster_has_no_needs_regardless_of_phase(self):
        assert dc.phase_aware_need_positions({"players": []}, {}, {}, {}, ["WR"], "rebuilding") == frozenset()
        assert dc.phase_aware_need_positions({"players": []}, {}, {}, {}, ["WR"], "contending") == frozenset()
