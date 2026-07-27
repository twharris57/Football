"""Tests for player_scoring.py's real-vs-baseline scoring formula and long-play bonuses.

Synthetic stat rows only, no real nfl_data_py calls — these are pure
functions over plain data structures, matching test_dynasty_core.py's style.
"""

from __future__ import annotations

import pandas as pd
import pytest

import player_scoring as ps

REAL_SCORING = {
    "pass_yd": 0.05,
    "pass_td": 6.0,
    "pass_int": -3.0,
    "rush_yd": 0.1,
    "rush_td": 6.0,
    "rush_fd": 0.5,
    "rec": 1.0,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "rec_fd": 0.5,
    "bonus_rec_te": 0.5,
    "fum_lost": -2.0,
}


def stat_row(**overrides) -> pd.Series:
    base = {
        "passing_yards": 0,
        "passing_tds": 0,
        "interceptions": 0,
        "passing_2pt_conversions": 0,
        "rushing_yards": 0,
        "rushing_tds": 0,
        "rushing_first_downs": 0,
        "rushing_2pt_conversions": 0,
        "receptions": 0,
        "receiving_yards": 0,
        "receiving_tds": 0,
        "receiving_first_downs": 0,
        "receiving_2pt_conversions": 0,
        "rushing_fumbles_lost": 0,
        "receiving_fumbles_lost": 0,
        "sack_fumbles_lost": 0,
    }
    base.update(overrides)
    return pd.Series(base)


class TestStatPoints:
    """_stat_points should isolate exactly the rules that differ between real and baseline."""

    def test_qb_real_points_include_league_pass_td_and_pass_yd_rate(self):
        row = stat_row(passing_yards=300, passing_tds=2, interceptions=1)

        real = ps._stat_points(row, REAL_SCORING, "QB")
        baseline = ps._stat_points(row, ps.BASELINE_SCORING, "QB")

        # Real: 300*0.05 + 2*6 - 1*3 = 24; baseline: 300*0.04 + 2*4 - 1*2 = 18.
        assert real == pytest.approx(24.0)
        assert baseline == pytest.approx(18.0)

    def test_te_premium_only_applies_to_te_position(self):
        row = stat_row(receptions=5, receiving_yards=50)

        te_real = ps._stat_points(row, REAL_SCORING, "TE")
        wr_real = ps._stat_points(row, REAL_SCORING, "WR")

        # TE gets the +0.5/reception premium on top of the same base points.
        assert te_real - wr_real == pytest.approx(5 * 0.5)

    def test_first_down_bonus_applies_to_any_position_in_real_but_not_baseline(self):
        row = stat_row(rushing_first_downs=4)

        real = ps._stat_points(row, REAL_SCORING, "RB")
        baseline = ps._stat_points(row, ps.BASELINE_SCORING, "RB")

        assert real == pytest.approx(4 * 0.5)
        assert baseline == pytest.approx(0.0)


class TestLongPlayBonusPoints:
    """Long-play bonuses require play-by-play data since weekly aggregates lose play length."""

    def test_credits_stack_for_a_touchdown_over_both_thresholds(self):
        pbp = pd.DataFrame(
            [
                {
                    "play_type": "run",
                    "yards_gained": 55.0,
                    "rush_touchdown": 1.0,
                    "pass_touchdown": 0.0,
                    "complete_pass": 0.0,
                    "rusher_player_id": "00-0001",
                    "passer_player_id": None,
                    "receiver_player_id": None,
                    "season": 2024,
                }
            ]
        )
        scoring = {"rush_td_40p": 2.0, "rush_td_50p": 3.0, "rush_40p": 2.0}

        bonus = ps._long_play_bonus_points(pbp, scoring)

        row = bonus[bonus["player_id"] == "00-0001"].iloc[0]
        # 55-yard rushing TD: rush_td_40p + rush_td_50p + rush_40p all trigger.
        assert row["long_play_points"] == pytest.approx(2.0 + 3.0 + 2.0)

    def test_no_bonus_below_threshold(self):
        pbp = pd.DataFrame(
            [
                {
                    "play_type": "run",
                    "yards_gained": 10.0,
                    "rush_touchdown": 1.0,
                    "pass_touchdown": 0.0,
                    "complete_pass": 0.0,
                    "rusher_player_id": "00-0001",
                    "passer_player_id": None,
                    "receiver_player_id": None,
                    "season": 2024,
                }
            ]
        )
        scoring = {"rush_td_40p": 2.0, "rush_td_50p": 3.0, "rush_40p": 2.0}

        bonus = ps._long_play_bonus_points(pbp, scoring)

        assert bonus.empty


class TestPickSixPenaltyPoints:
    """pass_int_td is a penalty on top of the flat per-interception rate, only
    when the interception itself gets returned for a touchdown - found during
    a one-time scoring_settings audit, not covered by _stat_points."""

    def test_penalizes_the_passer_on_an_interception_return_touchdown(self):
        pbp = pd.DataFrame(
            [
                {
                    "interception": 1.0,
                    "return_touchdown": 1.0,
                    "passer_player_id": "00-0001",
                    "season": 2024,
                }
            ]
        )
        scoring = {"pass_int_td": -6.0}

        penalty = ps._pick_six_penalty_points(pbp, scoring)

        row = penalty[penalty["player_id"] == "00-0001"].iloc[0]
        assert row["pick_six_points"] == pytest.approx(-6.0)

    def test_no_penalty_for_a_regular_interception(self):
        pbp = pd.DataFrame(
            [
                {
                    "interception": 1.0,
                    "return_touchdown": 0.0,
                    "passer_player_id": "00-0001",
                    "season": 2024,
                }
            ]
        )
        scoring = {"pass_int_td": -6.0}

        penalty = ps._pick_six_penalty_points(pbp, scoring)

        assert penalty.empty


class TestSaneRatio:
    """A ratio computed from a near-zero/negative baseline, or landing outside
    MULTIPLIER_BOUNDS, must be rejected rather than feeding a nonsense number
    into adj_value - a real risk for a qualifying-volume player with a
    genuinely bad season (heavy INTs, low yardage)."""

    def test_normal_ratio_is_returned(self):
        assert ps._sane_ratio(120.0, 100.0) == pytest.approx(1.2)

    def test_rejects_a_near_zero_baseline(self):
        # A huge ratio from an almost-zero denominator, e.g. a QB who barely
        # cleared the volume bar with a dreadful efficiency season.
        assert ps._sane_ratio(50.0, 0.5) is None

    def test_rejects_a_negative_baseline(self):
        # A heavy-INT, low-yardage season could make baseline_points negative -
        # dividing by it would invert the player's value entirely.
        assert ps._sane_ratio(20.0, -10.0) is None

    def test_rejects_a_ratio_outside_the_sane_band(self):
        assert ps._sane_ratio(500.0, 100.0) is None  # 5.0, way above the band
        assert ps._sane_ratio(10.0, 100.0) is None  # 0.1, way below the band
