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


class TestShrunkRatio:
    """A player's own ratio should blend toward the position average by
    volume, replacing the old all-or-nothing QUALIFYING_VOLUME cutoff with
    a smooth ramp - same shape as power_timeline.py's _shrunk_win_pct()."""

    def test_at_k_volume_own_ratio_gets_exactly_half_weight(self):
        # k = 200 (QB's QUALIFYING_VOLUME) - at volume == k, weight = 200/400 = 0.5.
        result = ps._shrunk_ratio(own_ratio=1.6, position_average=1.2, volume=200, k=200)

        assert result == pytest.approx((1.6 + 1.2) / 2)

    def test_thin_volume_leans_mostly_on_position_average(self):
        result = ps._shrunk_ratio(own_ratio=1.6, position_average=1.2, volume=1, k=200)

        assert result == pytest.approx(1.2, abs=0.01)

    def test_deep_volume_mostly_trusts_its_own_ratio(self):
        result = ps._shrunk_ratio(own_ratio=1.6, position_average=1.2, volume=10_000, k=200)

        assert result == pytest.approx(1.6, abs=0.01)

    def test_zero_volume_is_exactly_the_position_average(self):
        assert ps._shrunk_ratio(own_ratio=1.6, position_average=1.2, volume=0, k=200) == pytest.approx(1.2)


class TestBucketMetric:
    """_bucket_metric's direction must match BUCKET_LABELS' (low, high) ordering."""

    def test_qb_and_wr_bucket_on_forty_directly(self):
        rows = pd.DataFrame({"forty": [4.4, 5.0]})

        assert ps._bucket_metric("QB", rows).tolist() == [4.4, 5.0]
        assert ps._bucket_metric("WR", rows).tolist() == [4.4, 5.0]

    def test_rb_buckets_on_weight_directly(self):
        rows = pd.DataFrame({"wt": [190.0, 230.0]})

        assert ps._bucket_metric("RB", rows).tolist() == [190.0, 230.0]

    def test_te_composite_is_higher_for_heavier_slower_player(self):
        # Player A: light and fast (more "receiving"). Player B: heavy and slow (more "in_line").
        rows = pd.DataFrame({"wt": [220.0, 270.0], "forty": [4.5, 4.9]})

        composite = ps._bucket_metric("TE", rows)

        assert composite.iloc[0] < composite.iloc[1]

    def test_unknown_position_raises(self):
        with pytest.raises(ValueError):
            ps._bucket_metric("K", pd.DataFrame({"forty": [4.5]}))


def _qb_season_row(player_id: str, real_points: float, baseline_points: float) -> dict:
    # season_totals always carries every position's volume column (see
    # _season_totals_by_player's groupby), even for a QB-only test fixture -
    # _derive_rookie_buckets loops over every position in QUALIFYING_VOLUME.
    return {
        "player_id": player_id,
        "position": "QB",
        "attempts": 250,
        "carries": 0,
        "targets": 0,
        "real_points": real_points,
        "baseline_points": baseline_points,
    }


class TestDeriveRookieBuckets:
    """_derive_rookie_buckets should classify this year's rookies into a play-style
    bucket via combine data and assign that bucket's pooled ratio - explicitly
    rescoped to rookies only (valuation step A), with historical/veteran players
    only ever used to compute the bucket averages, never assigned one themselves."""

    def _patch_combine(self, monkeypatch, historical: pd.DataFrame, rookie: pd.DataFrame, crosswalk: pd.DataFrame):
        def fake_combine_data(years):
            return rookie if years == [2026] else historical

        monkeypatch.setattr(ps, "_combine_data", fake_combine_data)
        monkeypatch.setattr(ps, "_pfr_crosswalk", lambda: crosswalk)

    def test_rookie_assigned_the_matching_buckets_pooled_ratio(self, monkeypatch):
        # 12 low-forty ("mobile") historical QBs at a 1.2 ratio, 12 high-forty
        # ("pocket") at 1.5 - comfortably clears MIN_BUCKET_PLAYER_SEASONS (10) each.
        season_totals = pd.DataFrame(
            [_qb_season_row(f"gsis_low_{i}", 120.0, 100.0) for i in range(12)]
            + [_qb_season_row(f"gsis_high_{i}", 150.0, 100.0) for i in range(12)]
        )
        # Real combine data always carries every position's columns (wt, forty, ...)
        # regardless of position - included here even though QB doesn't bucket on wt,
        # since _derive_rookie_buckets' RB/WR/TE loop iterations read this same frame.
        historical = pd.DataFrame(
            [{"pos": "QB", "pfr_id": f"low_{i}", "forty": 4.5, "wt": 220.0} for i in range(12)]
            + [{"pos": "QB", "pfr_id": f"high_{i}", "forty": 5.0, "wt": 220.0} for i in range(12)]
        )
        rookie = pd.DataFrame([{"pos": "QB", "pfr_id": "rookie_mobile", "forty": 4.4, "wt": 220.0}])
        crosswalk = pd.DataFrame(
            [{"pfr_id": f"low_{i}", "gsis_id": f"gsis_low_{i}", "sleeper_id": pd.NA} for i in range(12)]
            + [{"pfr_id": f"high_{i}", "gsis_id": f"gsis_high_{i}", "sleeper_id": pd.NA} for i in range(12)]
            + [{"pfr_id": "rookie_mobile", "gsis_id": pd.NA, "sleeper_id": 999}]
        )
        self._patch_combine(monkeypatch, historical, rookie, crosswalk)

        result = ps._derive_rookie_buckets(season_totals, "2026")

        assert result == {"999": pytest.approx(1.2)}

    def test_rookie_without_a_crosswalk_match_is_skipped(self, monkeypatch):
        season_totals = pd.DataFrame(
            [_qb_season_row(f"gsis_low_{i}", 120.0, 100.0) for i in range(12)]
            + [_qb_season_row(f"gsis_high_{i}", 150.0, 100.0) for i in range(12)]
        )
        historical = pd.DataFrame(
            [{"pos": "QB", "pfr_id": f"low_{i}", "forty": 4.5, "wt": 220.0} for i in range(12)]
            + [{"pos": "QB", "pfr_id": f"high_{i}", "forty": 5.0, "wt": 220.0} for i in range(12)]
        )
        rookie = pd.DataFrame([{"pos": "QB", "pfr_id": "unmatched_rookie", "forty": 4.4, "wt": 220.0}])
        crosswalk = pd.DataFrame(
            [{"pfr_id": f"low_{i}", "gsis_id": f"gsis_low_{i}", "sleeper_id": pd.NA} for i in range(12)]
            + [{"pfr_id": f"high_{i}", "gsis_id": f"gsis_high_{i}", "sleeper_id": pd.NA} for i in range(12)]
            # No crosswalk row for "unmatched_rookie" at all.
        )
        self._patch_combine(monkeypatch, historical, rookie, crosswalk)

        result = ps._derive_rookie_buckets(season_totals, "2026")

        assert result == {}

    def test_position_skipped_when_historical_sample_too_small(self, monkeypatch):
        # Only 6 combine-matched historical QBs - below MIN_BUCKET_PLAYER_SEASONS * 2 (20).
        season_totals = pd.DataFrame([_qb_season_row(f"gsis_{i}", 120.0, 100.0) for i in range(6)])
        historical = pd.DataFrame([{"pos": "QB", "pfr_id": f"p{i}", "forty": 4.5, "wt": 220.0} for i in range(6)])
        rookie = pd.DataFrame([{"pos": "QB", "pfr_id": "rookie_a", "forty": 4.4, "wt": 220.0}])
        crosswalk = pd.DataFrame(
            [{"pfr_id": f"p{i}", "gsis_id": f"gsis_{i}", "sleeper_id": pd.NA} for i in range(6)]
            + [{"pfr_id": "rookie_a", "gsis_id": pd.NA, "sleeper_id": 999}]
        )
        self._patch_combine(monkeypatch, historical, rookie, crosswalk)

        result = ps._derive_rookie_buckets(season_totals, "2026")

        assert result == {}


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
