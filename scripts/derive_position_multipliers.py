"""Re-derive POSITION_VALUE_MULTIPLIER (see dynasty_core.py) from real stats.

Prints refreshed QB/TE multipliers for manual copy into
dynasty_core.POSITION_VALUE_MULTIPLIER — deliberately not auto-applied, so a
human sanity-checks the numbers (sample size, year-over-year swings) before
they affect live rankings.

Pulls the league's current season from Sleeper and looks back from there via
recent_complete_seasons_weekly_data(), so this script keeps working next year
unedited — only re-running it picks up a newly-published season. See
PROJECT_PLAN.md for the longer-term idea of running this automatically
instead of by hand.

    python scripts/derive_position_multipliers.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import dynasty_core as dc
import sleeper_api as sleeper

QB_MIN_ATTEMPTS = 200
TE_MIN_TARGETS = 30


def derive() -> None:
    league = sleeper.get_league(dc.DEFAULT_LEAGUE_ID)
    weekly = dc.recent_complete_seasons_weekly_data(league["season"], lookback=3)
    seasons = sorted(weekly["season"].unique())
    print(f"Pooling seasons: {seasons}")

    by_player_season = (
        weekly.groupby(["player_id", "player_name", "season", "position"], as_index=False)
        .agg(
            attempts=("attempts", "sum"),
            targets=("targets", "sum"),
            receptions=("receptions", "sum"),
            passing_tds=("passing_tds", "sum"),
            fantasy_points_ppr=("fantasy_points_ppr", "sum"),
        )
    )

    # FantasyCalc's assumed baseline (4pt passing, full PPR, no TE premium) is
    # what nfl_data_py's own fantasy_points_ppr already encodes. This league's
    # real rule differs from that baseline in exactly two places we correct
    # for here (see PROJECT_PLAN.md for the rest, still uncorrected):
    # 6pt passing TDs (+2/TD over baseline's 4) and a +0.5-per-reception TE
    # premium. Adding those deltas on top of fantasy_points_ppr holds every
    # other scoring setting constant, isolating just these two gaps.
    qb = by_player_season[
        (by_player_season["position"] == "QB") & (by_player_season["attempts"] >= QB_MIN_ATTEMPTS)
    ]
    qb_real = qb["fantasy_points_ppr"] + 2 * qb["passing_tds"]
    qb_multiplier = qb_real.sum() / qb["fantasy_points_ppr"].sum()
    print(f"QB: {len(qb)} qualifying player-seasons (>={QB_MIN_ATTEMPTS} attempts), multiplier = {qb_multiplier:.4f}")

    te = by_player_season[
        (by_player_season["position"] == "TE") & (by_player_season["targets"] >= TE_MIN_TARGETS)
    ]
    te_real = te["fantasy_points_ppr"] + 0.5 * te["receptions"]
    te_multiplier = te_real.sum() / te["fantasy_points_ppr"].sum()
    print(f"TE: {len(te)} qualifying player-seasons (>={TE_MIN_TARGETS} targets), multiplier = {te_multiplier:.4f}")

    print()
    print("Copy into dynasty_core.POSITION_VALUE_MULTIPLIER (round to 3 places):")
    print(f'    "QB": {qb_multiplier:.3f},')
    print(f'    "TE": {te_multiplier:.3f},')


if __name__ == "__main__":
    derive()
