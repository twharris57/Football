"""Re-runnable version of VA-4's two ad hoc scoring-correction checks.

`docs/rookie-draft-big-board.md`'s "Valuation" section documents two
one-off analyses with an explicit instruction to re-run them if a later
season's data looks different - neither was originally checked in
anywhere, so following that instruction meant reconstructing the queries
from scratch (CQ-12). This preserves both as one script:

1. Linearity check: does the per-player-season scoring-correction ratio
   (real_points / baseline_points) vary systematically with how many
   points a player scored, within a position? If it did, applying one
   flat ratio per player would risk compounding whatever convexity exists
   in how market value itself responds to points (see the doc's
   "Linearity assumption" subsection).
2. Continuous-vs-binary rookie bucket check: does a simple linear
   regression on the same combine metric `_bucket_metric()` already uses
   meaningfully outperform the current two-bucket-mean prediction? (see
   the doc's "Checked whether a continuous score... would meaningfully
   improve" subsection).

Standalone debug/sanity-check entry point, not something the app itself
needs to run - same spirit as derive_position_multipliers.py.

    python scripts/check_scoring_correction_assumptions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

import dynasty_core as dc
import player_scoring as ps
import sleeper_api as sleeper


def _season_totals_with_points(scoring_settings: dict[str, float], current_season: str) -> pd.DataFrame:
    """Reconstruct _derive_multipliers()'s season_totals (real_points/baseline_points
    per player-season) without reimplementing it - both checks below need this
    intermediate, which get_multipliers()'s public return value doesn't expose."""
    weekly = ps._recent_complete_seasons_weekly_data(current_season, ps.LOOKBACK_SEASONS)
    if weekly.empty:
        return pd.DataFrame()

    seasons = sorted(int(s) for s in weekly["season"].unique())
    pbp = ps._pbp_data_for_seasons(seasons)
    season_totals = ps._season_totals_by_player(weekly)

    long_play = ps._long_play_bonus_points(pbp, scoring_settings)
    season_totals = season_totals.merge(long_play, on=["player_id", "season"], how="left")
    season_totals["long_play_points"] = season_totals["long_play_points"].fillna(0.0)
    pick_six = ps._pick_six_penalty_points(pbp, scoring_settings)
    season_totals = season_totals.merge(pick_six, on=["player_id", "season"], how="left")
    season_totals["pick_six_points"] = season_totals["pick_six_points"].fillna(0.0)

    season_totals["real_points"] = season_totals.apply(
        lambda row: ps._stat_points(row, scoring_settings, row["position"])
        + row["long_play_points"]
        + row["pick_six_points"],
        axis=1,
    )
    season_totals["baseline_points"] = season_totals.apply(
        lambda row: ps._stat_points(row, ps.BASELINE_SCORING, row["position"]), axis=1
    )
    return season_totals


def check_linearity(season_totals: pd.DataFrame) -> None:
    print("=== Linearity check: does the ratio vary by value tier? ===")
    for position, (volume_col, min_volume) in ps.QUALIFYING_VOLUME.items():
        qualifying = season_totals[
            (season_totals["position"] == position) & (season_totals[volume_col] >= min_volume)
        ].copy()
        qualifying = qualifying[qualifying["baseline_points"] > ps.MIN_QUALIFYING_BASELINE_POINTS]
        if len(qualifying) < 3:
            print(f"  {position}: too few qualifying player-seasons ({len(qualifying)}), skipped")
            continue

        qualifying["ratio"] = qualifying["real_points"] / qualifying["baseline_points"]
        qualifying["tier"] = pd.qcut(qualifying["real_points"], 3, labels=["low", "mid", "high"], duplicates="drop")
        tier_means = qualifying.groupby("tier", observed=True)["ratio"].mean()
        corr = qualifying["real_points"].corr(qualifying["ratio"])
        spread = (tier_means.max() - tier_means.min()) / tier_means.mean()
        tiers_str = "/".join(f"{v:.4f}" for v in tier_means)
        print(f"  {position}: {tiers_str} (low/mid/high, n={len(qualifying)}, corr={corr:.2f}, spread={spread:.1%})")


def check_continuous_vs_binary_buckets(season_totals: pd.DataFrame) -> None:
    print()
    print("=== Continuous-vs-binary rookie bucket check ===")
    historical_combine = ps._combine_data(list(range(2000, 2025)))
    if historical_combine.empty:
        print("  no combine data available, skipped")
        return
    crosswalk = ps._pfr_crosswalk()
    historical_combine = historical_combine.merge(crosswalk, on="pfr_id", how="inner").dropna(subset=["gsis_id"])

    for position, (volume_col, min_volume) in ps.QUALIFYING_VOLUME.items():
        needed_cols = ["wt", "forty"] if position == "TE" else ["forty" if position in ("QB", "WR") else "wt"]
        qualifying = season_totals[
            (season_totals["position"] == position) & (season_totals[volume_col] >= min_volume)
        ]
        matched = historical_combine[historical_combine["pos"] == position].merge(
            qualifying, left_on="gsis_id", right_on="player_id", how="inner"
        )
        matched = matched.dropna(subset=needed_cols + ["baseline_points"])
        matched = matched[matched["baseline_points"] > ps.MIN_QUALIFYING_BASELINE_POINTS]
        if len(matched) < ps.MIN_BUCKET_PLAYER_SEASONS * 2:
            print(f"  {position}: too few combine-matched player-seasons ({len(matched)}), skipped")
            continue

        matched = matched.copy()
        matched["ratio"] = matched["real_points"] / matched["baseline_points"]
        metric = ps._bucket_metric(position, matched)
        corr = metric.corr(matched["ratio"])

        threshold = metric.median()
        bucket_pred = np.where(
            metric <= threshold,
            matched.loc[metric <= threshold, "ratio"].mean(),
            matched.loc[metric > threshold, "ratio"].mean(),
        )
        bucket_mse = float(np.mean((matched["ratio"].to_numpy() - bucket_pred) ** 2))

        slope, intercept = np.polyfit(metric, matched["ratio"], 1)
        regression_pred = slope * metric + intercept
        regression_mse = float(np.mean((matched["ratio"].to_numpy() - regression_pred.to_numpy()) ** 2))

        improvement_pct = (bucket_mse - regression_mse) / bucket_mse
        print(
            f"  {position}: metric-ratio corr={corr:+.2f}, n={len(matched)}, "
            f"regression MSE {improvement_pct:+.1%} lower than two-bucket-mean"
        )


def main() -> None:
    league = sleeper.get_league(dc.DEFAULT_LEAGUE_ID)
    season_totals = _season_totals_with_points(league["scoring_settings"], league["season"])
    if season_totals.empty:
        print("FAIL: no weekly data available to check assumptions against")
        sys.exit(1)

    check_linearity(season_totals)
    check_continuous_vs_binary_buckets(season_totals)
    print()
    print("OK: assumption checks complete")


if __name__ == "__main__":
    main()
