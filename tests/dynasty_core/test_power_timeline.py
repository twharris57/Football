"""Tests for dynasty_core.power_timeline."""

from __future__ import annotations

import pytest

import dynasty_core as dc
from tests.dynasty_core.helpers import fc_entry, make_player


class TestWeightedAverageAge:
    """A roster's timeline should weigh age by value, not average it flatly -
    an old bench piece shouldn't count the same as an old franchise player."""

    def test_weights_by_value_not_flat_average(self):
        players = {
            "old_star": make_player("WR", full_name="Old Star"),
            "young_bench": make_player("WR", full_name="Young Bench"),
        }
        players["old_star"]["age"] = 30
        players["young_bench"]["age"] = 22
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("old_star", 900), fc_entry("young_bench", 100)])
        roster = {"players": ["old_star", "young_bench"]}

        weighted = dc._weighted_average_age(roster, players, fc_by_id)

        # (30*900 + 22*100) / 1000 = 29.2, not the flat average of 26.
        assert weighted == pytest.approx(29.2)

    def test_none_when_no_player_has_both_age_and_value(self):
        players = {"p1": make_player("WR", full_name="P1")}
        players["p1"]["age"] = None
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("p1", 100)])
        roster = {"players": ["p1"]}

        assert dc._weighted_average_age(roster, players, fc_by_id) is None


class TestTeamPowerTimelineScores:
    """power_score should combine roster strength (VOR), timeline (weighted
    age), and actual record into one league-wide z-scored signal, recomputed
    fresh from current state - not any one signal alone, and not cached."""

    def test_stronger_older_winning_team_scores_higher(self):
        league = {"roster_positions": ["WR", "BN"]}
        players = {
            "a_wr": make_player("WR", full_name="A WR"),
            "b_wr": make_player("WR", full_name="B WR"),
        }
        players["a_wr"]["age"] = 29
        players["b_wr"]["age"] = 22
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("a_wr", 900), fc_entry("b_wr", 100)])
        rosters = [
            {"roster_id": 1, "players": ["a_wr"], "settings": {"wins": 10, "losses": 0, "ties": 0}},
            {"roster_id": 2, "players": ["b_wr"], "settings": {"wins": 0, "losses": 10, "ties": 0}},
        ]
        replacement_level = {"WR": 0.0, "QB": 0.0, "RB": 0.0, "TE": 0.0}

        scores = dc.team_power_timeline_scores(rosters, players, fc_by_id, replacement_level, league)

        assert scores.loc[1, "power_score"] > scores.loc[2, "power_score"]
        assert scores.loc[1, "phase"] == "contending"
        assert scores.loc[2, "phase"] == "rebuilding"
        # Team 1 is strictly stronger, so it ranks 1st (best) in the league.
        assert scores.loc[1, "rank"] == 1
        assert scores.loc[2, "rank"] == 2
        assert scores.loc[1, "games_played"] == 10
        assert scores.loc[2, "games_played"] == 10

    def test_zero_games_played_defaults_win_pct_to_neutral(self):
        league = {"roster_positions": ["WR", "BN"]}
        players = {
            "a_wr": make_player("WR", full_name="A WR"),
            "b_wr": make_player("WR", full_name="B WR"),
        }
        players["a_wr"]["age"] = 25
        players["b_wr"]["age"] = 25
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("a_wr", 500), fc_entry("b_wr", 500)])
        rosters = [
            {"roster_id": 1, "players": ["a_wr"], "settings": {}},
            {"roster_id": 2, "players": ["b_wr"], "settings": {}},
        ]
        replacement_level = {"WR": 0.0, "QB": 0.0, "RB": 0.0, "TE": 0.0}

        scores = dc.team_power_timeline_scores(rosters, players, fc_by_id, replacement_level, league)

        assert scores.loc[1, "win_pct"] == pytest.approx(0.5)
        assert scores.loc[2, "win_pct"] == pytest.approx(0.5)
        # Identical rosters, identical neutral win_pct - identical score, so
        # the neutral default genuinely contributed zero variance pre-season.
        assert scores.loc[1, "power_score"] == pytest.approx(scores.loc[2, "power_score"])
        # games_played=0 is exactly the signal a UI needs to show "this win%
        # is a placeholder, not a real record" instead of misreading it.
        assert scores.loc[1, "games_played"] == 0
        assert scores.loc[2, "games_played"] == 0

    def test_early_record_is_shrunk_toward_neutral(self):
        # Three identical rosters differing only in record: 0 games, a 1-0
        # start, and a settled 10-0 finish. Without shrinkage, 1-0 and 10-0
        # would both compute a raw win_pct of 1.0 and score identically -
        # the exact bug this test guards against.
        league = {"roster_positions": ["WR", "BN"]}
        players = {
            "a_wr": make_player("WR", full_name="A WR"),
            "b_wr": make_player("WR", full_name="B WR"),
            "c_wr": make_player("WR", full_name="C WR"),
        }
        for pid in ("a_wr", "b_wr", "c_wr"):
            players[pid]["age"] = 25
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("a_wr", 500), fc_entry("b_wr", 500), fc_entry("c_wr", 500)]
        )
        rosters = [
            {"roster_id": 1, "players": ["a_wr"], "settings": {}},
            {"roster_id": 2, "players": ["b_wr"], "settings": {"wins": 1, "losses": 0, "ties": 0}},
            {"roster_id": 3, "players": ["c_wr"], "settings": {"wins": 10, "losses": 0, "ties": 0}},
        ]
        replacement_level = {"WR": 0.0, "QB": 0.0, "RB": 0.0, "TE": 0.0}

        scores = dc.team_power_timeline_scores(rosters, players, fc_by_id, replacement_level, league)

        # win_pct is the RAW, unshrunk record - both the 1-0 and 10-0 teams
        # are a real 100% record and must display as such, not as the
        # statistical prior fed to the score (see valuation_principles.md's
        # "a field used as both an internal score input and a user-facing
        # label needs two names" rule).
        assert scores.loc[2, "win_pct"] == pytest.approx(1.0)
        assert scores.loc[3, "win_pct"] == pytest.approx(1.0)
        # win_pct_shrunk is what actually feeds the z-scoring: a 1-0 start
        # should be pulled well below a settled 10-0 record...
        assert scores.loc[2, "win_pct_shrunk"] < scores.loc[3, "win_pct_shrunk"]
        # ...and still above the neutral 0-games baseline, not collapsed to it.
        assert scores.loc[1, "win_pct_shrunk"] < scores.loc[2, "win_pct_shrunk"]
        # Same ordering should carry through to the blended score.
        assert scores.loc[1, "power_score"] < scores.loc[2, "power_score"] < scores.loc[3, "power_score"]

    def test_single_team_league_does_not_crash(self):
        # Population std (ddof=0) of one team is 0, not NaN - guards the
        # single-row edge case a sample std would hit.
        league = {"roster_positions": ["WR", "BN"]}
        players = {"a_wr": make_player("WR", full_name="A WR")}
        players["a_wr"]["age"] = 25
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("a_wr", 500)])
        rosters = [{"roster_id": 1, "players": ["a_wr"], "settings": {}}]
        replacement_level = {"WR": 0.0, "QB": 0.0, "RB": 0.0, "TE": 0.0}

        scores = dc.team_power_timeline_scores(rosters, players, fc_by_id, replacement_level, league)

        assert scores.loc[1, "power_score"] == pytest.approx(0.0)
        assert scores.loc[1, "phase"] == "treading_water"

    def test_quality_and_timeline_axes_can_disagree_within_one_team(self):
        # A young, strong, winning roster is exactly the case power_score
        # alone hides: it's "quality strong" (high VOR + winning) but
        # "timeline rebuild-pointed" (young) at the same time - two signals
        # a trade evaluator needs to tell apart, not average together.
        league = {"roster_positions": ["WR", "BN"]}
        players = {
            "a_wr": make_player("WR", full_name="A WR"),
            "b_wr": make_player("WR", full_name="B WR"),
        }
        players["a_wr"]["age"] = 22
        players["b_wr"]["age"] = 32
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("a_wr", 900), fc_entry("b_wr", 100)])
        rosters = [
            {"roster_id": 1, "players": ["a_wr"], "settings": {"wins": 10, "losses": 0, "ties": 0}},
            {"roster_id": 2, "players": ["b_wr"], "settings": {"wins": 0, "losses": 10, "ties": 0}},
        ]
        replacement_level = {"WR": 0.0, "QB": 0.0, "RB": 0.0, "TE": 0.0}

        scores = dc.team_power_timeline_scores(rosters, players, fc_by_id, replacement_level, league)

        # Team 1: strong quality (high VOR + winning) ...
        assert scores.loc[1, "quality_score"] > 0
        # ... but timeline says rebuild (young), not win-now - the opposite
        # sign from quality_score, which power_score's single blended
        # number can't surface.
        assert scores.loc[1, "timeline_score"] < 0
        assert scores.loc[2, "quality_score"] < 0
        assert scores.loc[2, "timeline_score"] > 0
        # quality_score is the average of the vor/win_pct z-scores only.
        assert scores.loc[1, "quality_score"] == pytest.approx(-scores.loc[2, "quality_score"])
        assert scores.loc[1, "timeline_score"] == pytest.approx(-scores.loc[2, "timeline_score"])
