"""Per-player real-scoring correction for FantasyCalc values.

Ratio = a player's points under league scoring ÷ points under `BASELINE_SCORING`,
shrunk toward the position average by volume. Doesn't import `dynasty_core`, which
imports this module.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import nfl_data_py as nfl
import pandas as pd
from cache_dir import CACHE_DIR

logger = logging.getLogger(__name__)

MULTIPLIERS_CACHE_PATH = CACHE_DIR / "scoring_multipliers.json"

LOOKBACK_SEASONS = 3

# Single-season "meaningful starter" volume. It filters which seasons feed
# position_average, and × LOOKBACK_SEASONS it's the shrinkage k (half weight on a
# player's own ratio).
QUALIFYING_VOLUME: dict[str, tuple[str, int]] = {
    "QB": ("attempts", 200),
    "RB": ("carries", 100),
    "WR": ("targets", 50),
    "TE": ("targets", 30),
}

# Reject ratios from a near-zero baseline or outside these bounds; real ones land in
# [1.08, 1.61]. Rejected ratios fall back a step.
MIN_QUALIFYING_BASELINE_POINTS = 1.0
MULTIPLIER_BOUNDS = (0.5, 2.0)


def _sane_ratio(real_points: float, baseline_points: float) -> float | None:
    """real_points / baseline_points, or None if the input/result isn't trustworthy."""
    if baseline_points <= MIN_QUALIFYING_BASELINE_POINTS:
        return None
    ratio = real_points / baseline_points
    if not (MULTIPLIER_BOUNDS[0] <= ratio <= MULTIPLIER_BOUNDS[1]):
        return None
    return ratio


def _shrunk_ratio(own_ratio: float, position_average: float, volume: float, k: int) -> float:
    """Blend `own_ratio` toward `position_average` with weight `volume / (volume + k)`."""
    weight = volume / (volume + k)
    return weight * own_ratio + (1 - weight) * position_average


# Rookies have no NFL stats, so combine data splits each position into two play-style
# buckets at the historical median. Rookies without a combine number use
# position_average. Labels are (low metric, high metric):
#   QB: 40-yd - mobile / pocket
#   RB: weight - receiving back / early-down
#   WR: 40-yd - deep threat / possession
#   TE: weight + 40 z-score - receiving / in-line
BUCKET_LABELS: dict[str, tuple[str, str]] = {
    "QB": ("mobile", "pocket"),
    "RB": ("receiving_back", "early_down"),
    "WR": ("deep_threat", "possession"),
    "TE": ("receiving", "in_line"),
}

# Minimum player-seasons for a bucket ratio; real buckets have 77-203.
MIN_BUCKET_PLAYER_SEASONS = 10


def _z_scores(series: pd.Series) -> pd.Series:
    std = series.std()
    if not std:
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def _bucket_metric(position: str, rows: pd.DataFrame) -> pd.Series:
    """Per-row score; higher means more of `BUCKET_LABELS[position][1]`."""
    if position in ("QB", "WR"):
        return rows["forty"]
    if position == "RB":
        return rows["wt"]
    if position == "TE":
        return _z_scores(rows["wt"]) + _z_scores(rows["forty"])
    raise ValueError(f"no bucket metric defined for position {position!r}")


def _combine_data(years: list[int]) -> pd.DataFrame:
    try:
        return nfl.import_combine_data(years=years, positions=list(BUCKET_LABELS))
    except Exception:
        logger.warning("nfl_data_py has no combine data for %s; rookie play-style buckets skipped", years)
        return pd.DataFrame()


def _pfr_crosswalk() -> pd.DataFrame:
    ids = nfl.import_ids().dropna(subset=["pfr_id"])
    return ids[["pfr_id", "gsis_id", "sleeper_id"]]


def _derive_rookie_buckets(season_totals: pd.DataFrame, current_season: str) -> dict[str, float]:
    """`{sleeper_id: ratio}` for this year's rookie class, by play-style bucket."""
    historical_combine = _combine_data(list(range(2000, int(current_season))))
    rookie_combine = _combine_data([int(current_season)])
    if historical_combine.empty or rookie_combine.empty:
        return {}

    crosswalk = _pfr_crosswalk()
    historical_combine = historical_combine.merge(crosswalk, on="pfr_id", how="inner").dropna(subset=["gsis_id"])
    rookie_combine = rookie_combine.merge(crosswalk, on="pfr_id", how="inner").dropna(subset=["sleeper_id"])

    bucket_ratio: dict[str, float] = {}
    for position, (volume_col, min_volume) in QUALIFYING_VOLUME.items():
        needed_cols = ["wt", "forty"] if position == "TE" else ["forty" if position in ("QB", "WR") else "wt"]

        qualifying = season_totals[
            (season_totals["position"] == position) & (season_totals[volume_col] >= min_volume)
        ]
        historical = historical_combine[historical_combine["pos"] == position].merge(
            qualifying, left_on="gsis_id", right_on="player_id", how="inner"
        )
        historical = historical.dropna(subset=needed_cols)
        if len(historical) < MIN_BUCKET_PLAYER_SEASONS * 2:
            continue

        rookies = rookie_combine[rookie_combine["pos"] == position].dropna(subset=needed_cols)
        if rookies.empty:
            continue

        metric = _bucket_metric(position, historical)
        threshold = metric.median()
        low_label, high_label = BUCKET_LABELS[position]

        for label, mask in ((low_label, metric <= threshold), (high_label, metric > threshold)):
            bucket_rows = historical[mask]
            if len(bucket_rows) < MIN_BUCKET_PLAYER_SEASONS:
                continue
            ratio = _sane_ratio(bucket_rows["real_points"].sum(), bucket_rows["baseline_points"].sum())
            if ratio is None:
                continue
            rookie_metric = _bucket_metric(position, rookies)
            rookie_mask = rookie_metric <= threshold if label == low_label else rookie_metric > threshold
            for sleeper_id in rookies.loc[rookie_mask, "sleeper_id"]:
                bucket_ratio[str(int(sleeper_id))] = ratio

    return bucket_ratio

# FantasyCalc's scoring is unpublished; assumed standard: 4pt pass TD, -2 INT/fumble,
# full PPR, no TE premium, no first-down or long-play bonuses.
BASELINE_SCORING: dict[str, float] = {
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "pass_int": -2.0,
    "rush_yd": 0.1,
    "rush_td": 6.0,
    "rec": 1.0,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "fum_lost": -2.0,
    "pass_2pt": 2.0,
    "rush_2pt": 2.0,
    "rec_2pt": 2.0,
}

# Yardage-gated bonuses that need play-by-play. They're separate categories, so one
# long play can earn several.
LONG_PLAY_THRESHOLDS = {
    "pass_td_40p": 40,
    "pass_td_50p": 50,
    "rush_td_40p": 40,
    "rush_td_50p": 50,
    "rec_td_40p": 40,
    "rec_td_50p": 50,
    "rush_40p": 40,
    "rec_40p": 40,
    "pass_cmp_40p": 40,
}


def _recent_complete_seasons_weekly_data(current_season: str, lookback: int) -> pd.DataFrame:
    """Copy of `dynasty_core`'s season lookback, duplicated to avoid a circular import."""
    candidate = int(current_season) - 1
    frames = []
    while len(frames) < lookback and candidate > 2000:
        try:
            frames.append(nfl.import_weekly_data([candidate]))
        except Exception:
            logger.info("nfl_data_py has no weekly data for %s yet, trying %s", candidate, candidate - 1)
        candidate -= 1
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _pbp_data_for_seasons(seasons: list[int]) -> pd.DataFrame:
    """Play-by-play for exactly the weekly data's seasons, so bonuses land in the right season.

    A missing season just skips its long-play bonuses.
    """
    frames = []
    for season in seasons:
        try:
            frames.append(nfl.import_pbp_data([season], downcast=True))
        except Exception:
            logger.warning("nfl_data_py has no play-by-play data for %s; skipping long-play bonuses for it", season)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _stat_points(totals: pd.Series, scoring: dict[str, float], position: str) -> float:
    """Counting-stat points under `scoring`. `BASELINE_SCORING` omits the league-only rules."""
    points = 0.0
    points += totals["passing_yards"] * scoring.get("pass_yd", 0.0)
    points += totals["passing_tds"] * scoring.get("pass_td", 0.0)
    points += totals["interceptions"] * scoring.get("pass_int", 0.0)
    points += totals["passing_2pt_conversions"] * scoring.get("pass_2pt", 0.0)
    points += totals["rushing_yards"] * scoring.get("rush_yd", 0.0)
    points += totals["rushing_tds"] * scoring.get("rush_td", 0.0)
    points += totals["rushing_first_downs"] * scoring.get("rush_fd", 0.0)
    points += totals["rushing_2pt_conversions"] * scoring.get("rush_2pt", 0.0)
    points += totals["receptions"] * scoring.get("rec", 0.0)
    points += totals["receiving_yards"] * scoring.get("rec_yd", 0.0)
    points += totals["receiving_tds"] * scoring.get("rec_td", 0.0)
    points += totals["receiving_first_downs"] * scoring.get("rec_fd", 0.0)
    points += totals["receiving_2pt_conversions"] * scoring.get("rec_2pt", 0.0)
    if position == "TE":
        points += totals["receptions"] * scoring.get("bonus_rec_te", 0.0)
    fumbles_lost = (
        totals["rushing_fumbles_lost"] + totals["receiving_fumbles_lost"] + totals["sack_fumbles_lost"]
    )
    points += fumbles_lost * scoring.get("fum_lost", 0.0)
    return points


def _long_play_bonus_points(pbp: pd.DataFrame, scoring: dict[str, float]) -> pd.DataFrame:
    """Long-play bonus points per player-season: columns `player_id`, `season`, `long_play_points`."""
    if pbp.empty:
        return pd.DataFrame(columns=["player_id", "season", "long_play_points"])

    plays = pbp[pbp["play_type"].isin(["pass", "run"])].copy()
    credits: list[dict[str, Any]] = []

    def add_credits(mask: pd.Series, player_col: str, key: str) -> None:
        threshold = LONG_PLAY_THRESHOLDS[key]
        value = scoring.get(key, 0.0)
        if value == 0.0:
            return
        rows = plays[mask & (plays["yards_gained"] >= threshold) & plays[player_col].notna()]
        for player_id, season in zip(rows[player_col], rows["season"]):
            credits.append({"player_id": player_id, "season": season, "long_play_points": value})

    is_complete_pass = (plays["play_type"] == "pass") & (plays["complete_pass"].fillna(0).astype(bool))
    is_run = plays["play_type"] == "run"
    is_pass_td = plays["pass_touchdown"].fillna(0).astype(bool)
    is_rush_td = plays["rush_touchdown"].fillna(0).astype(bool)

    add_credits(is_pass_td, "passer_player_id", "pass_td_40p")
    add_credits(is_pass_td, "passer_player_id", "pass_td_50p")
    add_credits(is_pass_td, "receiver_player_id", "rec_td_40p")
    add_credits(is_pass_td, "receiver_player_id", "rec_td_50p")
    add_credits(is_rush_td, "rusher_player_id", "rush_td_40p")
    add_credits(is_rush_td, "rusher_player_id", "rush_td_50p")
    add_credits(is_run, "rusher_player_id", "rush_40p")
    add_credits(is_complete_pass, "receiver_player_id", "rec_40p")
    add_credits(is_complete_pass, "passer_player_id", "pass_cmp_40p")

    if not credits:
        return pd.DataFrame(columns=["player_id", "season", "long_play_points"])
    df = pd.DataFrame(credits)
    return df.groupby(["player_id", "season"], as_index=False)["long_play_points"].sum()


def _pick_six_penalty_points(pbp: pd.DataFrame, scoring: dict[str, float]) -> pd.DataFrame:
    """`pass_int_td` penalties per player-season (needs play-by-play): `player_id`, `season`, `pick_six_points`."""
    value = scoring.get("pass_int_td", 0.0)
    if pbp.empty or value == 0.0:
        return pd.DataFrame(columns=["player_id", "season", "pick_six_points"])

    pick_sixes = pbp[
        (pbp["interception"].fillna(0).astype(bool))
        & (pbp["return_touchdown"].fillna(0).astype(bool))
        & pbp["passer_player_id"].notna()
    ]
    if pick_sixes.empty:
        return pd.DataFrame(columns=["player_id", "season", "pick_six_points"])

    credits = pd.DataFrame(
        {
            "player_id": pick_sixes["passer_player_id"],
            "season": pick_sixes["season"],
            "pick_six_points": value,
        }
    )
    return credits.groupby(["player_id", "season"], as_index=False)["pick_six_points"].sum()


def _season_totals_by_player(weekly: pd.DataFrame) -> pd.DataFrame:
    """Sum weekly stats into one row per player-season, keeping the columns _stat_points needs."""
    stat_cols = [
        "attempts",
        "carries",
        "targets",
        "receptions",
        "passing_yards",
        "passing_tds",
        "interceptions",
        "passing_2pt_conversions",
        "rushing_yards",
        "rushing_tds",
        "rushing_first_downs",
        "rushing_2pt_conversions",
        "receiving_yards",
        "receiving_tds",
        "receiving_first_downs",
        "receiving_2pt_conversions",
        "rushing_fumbles_lost",
        "receiving_fumbles_lost",
        "sack_fumbles_lost",
    ]
    return weekly.groupby(["player_id", "player_name", "season", "position"], as_index=False)[stat_cols].sum()


def gsis_to_sleeper_crosswalk() -> dict[str, str]:
    """`{gsis_id: sleeper_id}`. Last row wins on collisions; real conflicts are logged."""
    ids = nfl.import_ids().dropna(subset=["gsis_id", "sleeper_id"])
    distinct_targets = ids.groupby("gsis_id")["sleeper_id"].nunique()
    conflicts = distinct_targets[distinct_targets > 1]
    if not conflicts.empty:
        logger.warning(
            "nfl_data_py's ID crosswalk has %d gsis_id value(s) mapping to more than one "
            "sleeper_id - using whichever row comes last for each: %s",
            len(conflicts),
            ", ".join(conflicts.index[:5]),
        )
    return {row.gsis_id: str(int(row.sleeper_id)) for row in ids.itertuples()}


def _derive_multipliers(scoring_settings: dict[str, float], current_season: str) -> dict[str, Any]:
    weekly = _recent_complete_seasons_weekly_data(current_season, LOOKBACK_SEASONS)
    if weekly.empty:
        return {"seasons": [], "per_player": {}, "position_average": {}}

    seasons = sorted(int(s) for s in weekly["season"].unique())
    pbp = _pbp_data_for_seasons(seasons)
    season_totals = _season_totals_by_player(weekly)
    long_play = _long_play_bonus_points(pbp, scoring_settings)
    season_totals = season_totals.merge(long_play, on=["player_id", "season"], how="left")
    season_totals["long_play_points"] = season_totals["long_play_points"].fillna(0.0)
    pick_six = _pick_six_penalty_points(pbp, scoring_settings)
    season_totals = season_totals.merge(pick_six, on=["player_id", "season"], how="left")
    season_totals["pick_six_points"] = season_totals["pick_six_points"].fillna(0.0)

    season_totals["real_points"] = season_totals.apply(
        lambda row: _stat_points(row, scoring_settings, row["position"])
        + row["long_play_points"]
        + row["pick_six_points"],
        axis=1,
    )
    season_totals["baseline_points"] = season_totals.apply(
        lambda row: _stat_points(row, BASELINE_SCORING, row["position"]), axis=1
    )

    gsis_to_sleeper = gsis_to_sleeper_crosswalk()

    per_player: dict[str, float] = {}
    position_average: dict[str, float] = {}
    for position, (volume_col, min_volume) in QUALIFYING_VOLUME.items():
        qualifying = season_totals[
            (season_totals["position"] == position) & (season_totals[volume_col] >= min_volume)
        ]
        if qualifying.empty:
            continue
        pos_ratio = _sane_ratio(qualifying["real_points"].sum(), qualifying["baseline_points"].sum())
        if pos_ratio is None:
            # No trustworthy anchor: skip this position's per-player ratios too.
            continue
        position_average[position] = pos_ratio

        # Any volume counts; shrinkage weights thin samples.
        position_rows = season_totals[season_totals["position"] == position]
        shrinkage_k = min_volume * LOOKBACK_SEASONS
        for player_id, group in position_rows.groupby("player_id"):
            own_ratio = _sane_ratio(group["real_points"].sum(), group["baseline_points"].sum())
            if own_ratio is None:
                continue
            sleeper_id = gsis_to_sleeper.get(player_id)
            if sleeper_id is None:
                continue
            total_volume = group[volume_col].sum()
            per_player[sleeper_id] = _shrunk_ratio(own_ratio, pos_ratio, total_volume, shrinkage_k)

    rookie_bucket = _derive_rookie_buckets(season_totals, current_season)

    return {
        "seasons": seasons,
        "per_player": per_player,
        "position_average": position_average,
        "rookie_bucket": rookie_bucket,
    }


def get_multipliers(scoring_settings: dict[str, float], current_season: str, force_refresh: bool = False) -> dict[str, Any]:
    """Return `{seasons, per_player, position_average, rookie_bucket}` ratios.

    Cached with no TTL (historical data). `force_refresh` (1-2 min) runs only from the
    explicit Advanced-refresh option or `derive_position_multipliers.py`.
    """
    if not force_refresh and MULTIPLIERS_CACHE_PATH.exists():
        cached = json.loads(MULTIPLIERS_CACHE_PATH.read_text(encoding="utf-8"))
        return {
            "seasons": cached["seasons"],
            "per_player": cached["per_player"],
            "position_average": cached["position_average"],
            "rookie_bucket": cached.get("rookie_bucket", {}),
        }

    logger.info("Recomputing real-scoring multipliers from nfl_data_py (weekly + play-by-play)...")
    result = _derive_multipliers(scoring_settings, current_season)

    CACHE_DIR.mkdir(exist_ok=True)
    MULTIPLIERS_CACHE_PATH.write_text(
        json.dumps({**result, "computed_at": time.time()}),
        encoding="utf-8",
    )
    return result
