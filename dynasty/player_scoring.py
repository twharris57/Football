"""Per-player real-scoring recompute: a personalized FantasyCalc correction ratio.

For every player with any real NFL volume, computes their own points under
this league's actual `scoring_settings` divided by their points under
FantasyCalc's assumed baseline model (`BASELINE_SCORING`), then shrinks
that ratio toward the position average by volume (`_shrunk_ratio()`) - a
thin sample leans heavily on the position average, a deep one mostly
trusts its own signal, with no hard cutoff between the two. See
docs/rookie-draft-big-board.md's "Valuation" section for the full
methodology and rationale.

Deliberately independent of dynasty_core (no import of it): those modules
import this one to call get_multipliers(), so this module can't import them
back without a circular import.
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

# Two roles, on two different scales: (1) the *single-season* volume bar
# `position_average` itself pools from - only "meaningful starter" seasons
# count toward that anchor, same spirit as step E's original QB/TE bars,
# extended here to RB/WR since first-down and long-play bonuses apply to
# them too; (2) the basis for each position's shrinkage constant k, used
# below scaled by LOOKBACK_SEASONS - at that many *lookback-window* (career)
# volume units, a player's own ratio gets exactly half weight against
# position_average, the same shape as power_timeline.py's
# WIN_PCT_SHRINKAGE_K/_shrunk_win_pct(). Using this bar unscaled as k would
# silently reuse a single-season number against a multi-season sum (VA-9).
QUALIFYING_VOLUME: dict[str, tuple[str, int]] = {
    "QB": ("attempts", 200),
    "RB": ("carries", 100),
    "WR": ("targets", 50),
    "TE": ("targets", 30),
}

# A ratio computed from a pooled baseline_points at or below this isn't a
# trustworthy denominator - a qualifying-volume player with a genuinely bad
# season (heavy INTs, low yardage) can have baseline_points near zero or
# negative, which would blow up or invert the resulting ratio. Observed
# real ratios across a 332-player sample land in [1.08, 1.61] - MULTIPLIER_BOUNDS
# gives real headroom around that while still rejecting a clearly broken
# input; a rejected ratio falls back further up the chain (position average,
# then the hardcoded POSITION_VALUE_MULTIPLIER constant) rather than feeding
# a nonsense number into adj_value.
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
    """Blend a player's own sane ratio toward the position average, weighted by volume.

    Replaces the old hard `QUALIFYING_VOLUME` cutoff (0% weight on a
    player's own signal below the bar, 100% at/above it) with a smooth
    ramp - a player sitting exactly at `k` (today's old bar) gets their own
    ratio at half weight, not an all-or-nothing flip. Same shape as
    `power_timeline.py`'s `_shrunk_win_pct()`.
    """
    weight = volume / (volume + k)
    return weight * own_ratio + (1 - weight) * position_average


# Valuation step A: rookies have no real NFL history, so they always fall
# back to the flat per-position average ratio above - but that one number
# doesn't distinguish a mobile QB from a pocket passer, or a receiving TE
# from an in-line blocker, even though this league's scoring gap (6pt
# passing TDs, TE reception premium, long-play bonuses) plausibly affects
# those two profiles differently. This splits each position into two
# play-style buckets using NFL Scouting Combine testing data
# (`import_combine_data`), a real per-rookie athletic signal available
# without college stats: each qualifying *historical* player (same
# QUALIFYING_VOLUME bar as above) who has a matched combine record is
# assigned a bucket by a simple median split on the metric below, bucket
# ratios are pooled the same way position_average is, and this year's
# incoming rookies are assigned to a bucket by the same threshold via their
# own combine number. A rookie with no combine record, or no number for
# the position's metric (QBs skip the 40 more often than other positions),
# simply isn't in the result dict and falls back to position_average
# instead - a real coverage gap, not a bug (see docs).
#
# Labels are (low-metric-value bucket, high-metric-value bucket):
#   QB: 40-yd dash - faster (lower) => mobile; slower => pocket. Rushing
#       production isn't boosted by the 6pt passing-TD rule the way pocket
#       passing volume is, so a mobile QB's true ratio plausibly differs
#       from a pocket passer's.
#   RB: weight - lighter => receiving back; heavier => early-down/power.
#       Reception/first-down bonuses matter more to receiving-back usage.
#   WR: 40-yd dash - faster (lower) => deep threat; slower => possession.
#       The 40p/50p long-play bonuses reward exactly the deep-threat profile.
#   TE: weight+40 composite (z-scored, summed) - lower => receiving;
#       higher => in-line/blocking. Receiving TEs earn more of the TE
#       reception premium than blocking-heavy TEs who see fewer targets.
BUCKET_LABELS: dict[str, tuple[str, str]] = {
    "QB": ("mobile", "pocket"),
    "RB": ("receiving_back", "early_down"),
    "WR": ("deep_threat", "possession"),
    "TE": ("receiving", "in_line"),
}

# Below this many combine-matched qualifying player-seasons in a bucket, the
# pooled ratio is too noisy to trust - skip that bucket (its rookies fall
# back to position_average) rather than publish a number from a handful of
# player-seasons. Real observed counts (77-203 combine-matched
# player-seasons per position, see docs) comfortably clear this in normal
# operation; this is a defensive floor, not a normal code path.
MIN_BUCKET_PLAYER_SEASONS = 10


def _z_scores(series: pd.Series) -> pd.Series:
    std = series.std()
    if not std:
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def _bucket_metric(position: str, rows: pd.DataFrame) -> pd.Series:
    """Score per row; a HIGHER score means more of BUCKET_LABELS[position][1] (see above)."""
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
    """{sleeper_id: ratio} for this year's incoming rookie class, bucketed by play style.

    Only ever produces entries for players in this year's combine class
    (`current_season`) - explicitly rescoped to rookies, not a general
    veteran-inclusive bucket system (see PROJECT_PLAN_DYNASTY.md step A).
    """
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

# FantasyCalc doesn't publish its scoring assumptions. This is the explicit,
# documented baseline this project assumes (matches what step E's script
# implicitly assumed via nfl_data_py's own fantasy_points_ppr column):
# standard 4pt passing TD, -2 INT/fumble-lost, full PPR, 6pt rush/rec TD,
# standard yardage rates, no TE premium, no first-down or long-play bonuses.
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

# Sleeper scoring keys for the per-play, yardage-gated bonuses that require
# play-by-play data to compute (weekly aggregates don't preserve individual
# play length). Each is checked independently against the actual league
# scoring_settings - a single long play can trigger more than one of these
# at once (e.g. a 55-yard TD pass can earn both the 40+ and 50+ TD bonus),
# since Sleeper models them as separate stat categories, not exclusive tiers.
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
    """Same lookback-from-current-season pattern as dynasty_core's helper.

    Duplicated rather than imported to keep this module free of a circular
    dependency on dynasty_core.py (which imports this module).
    """
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
    """Play-by-play data for exactly the given seasons.

    Deliberately keyed to weekly data's own confirmed season list (see
    _derive_multipliers) rather than running its own independent backward
    lookback - weekly and play-by-play data don't necessarily get published
    on the same schedule, so two separate lookback loops could land on
    different season sets and silently misattribute long-play bonuses to
    the wrong season (or drop them) wherever the two disagreed. A season
    missing play-by-play here just skips long-play bonuses for it - not
    fatal, since they're the smaller of the corrections being made.
    """
    frames = []
    for season in seasons:
        try:
            frames.append(nfl.import_pbp_data([season], downcast=True))
        except Exception:
            logger.warning("nfl_data_py has no play-by-play data for %s; skipping long-play bonuses for it", season)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _stat_points(totals: pd.Series, scoring: dict[str, float], position: str) -> float:
    """Points from ordinary counting stats under the given scoring rules.

    Works for both the real league's scoring_settings and BASELINE_SCORING -
    the baseline dict simply omits rush_fd/rec_fd/bonus_rec_te, defaulting
    to 0 via .get(), so calling this with either dict isolates exactly the
    rules that actually differ.
    """
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
    """Per-player-season bonus points from yardage-gated categories (see LONG_PLAY_THRESHOLDS).

    Returns columns [player_id, season, long_play_points] - one row per
    player-season that earned at least one such bonus.
    """
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
    """Per-player-season penalty points for a passer's interception returned for a TD.

    Found via a one-time scoring_settings audit: this league's real
    `pass_int_td: -6.0` is a penalty on top of the flat `pass_int` per-
    interception penalty, only on interceptions that get returned for a
    touchdown - not covered by _stat_points (which only knows the flat
    per-INT rate) or weekly data (which has no return-touchdown detail),
    so it needs the same play-by-play source as the long-play bonuses.
    Returns columns [player_id, season, pick_six_points] - one row per
    player-season with at least one such interception.
    """
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
    """{gsis_id: sleeper_id} crosswalk from nfl_data_py's ID table.

    Shared with `dynasty_core.handcuff_map`, which needs the identical
    mapping - a single implementation instead of two copies of the same
    collision handling. Keeps whichever row comes last for a colliding
    gsis_id (arbitrary but deterministic), and logs a warning when that
    collision is a genuine conflict (the same gsis_id mapping to more than
    one distinct sleeper_id) - a data-quality problem in the upstream
    crosswalk this project can't fix at the source.
    """
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
            # No trustworthy anchor to shrink toward this position - skip
            # per_player too rather than using an unblended, unshrunk ratio.
            continue
        position_average[position] = pos_ratio

        # Every player at this position with any real volume in the
        # lookback window, not just those clearing the old per-season
        # qualifying bar - _shrunk_ratio() lets a thin sample contribute
        # partial signal instead of being discarded outright, and
        # _sane_ratio() below still rejects a player whose own summed
        # ratio isn't trustworthy at all (e.g. too little baseline_points).
        position_rows = season_totals[season_totals["position"] == position]
        # min_volume is a *single-season* qualifying bar, but total_volume
        # below is summed across the whole LOOKBACK_SEASONS window - scale
        # the bar the same way so k means "one lookback-window's worth of
        # qualifying-level play," not "one season's worth" (see VA-9,
        # valuation_principles.md's shrinkage-constant-scaling rule).
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
    """Return {"seasons": [...], "per_player": {sleeper_id: ratio}, "position_average": {pos: ratio},
    "rookie_bucket": {sleeper_id: ratio}}.

    Cached to disk with no TTL, unlike sleeper_api's players cache - the
    underlying data is entirely historical/complete seasons, so nothing
    changes between refreshes except once a year when a new season's stats
    are published. A routine Refresh/Advanced-refresh-players-only click
    never passes `force_refresh=True` here (a 1-2 minute synchronous pull,
    unsuitable to trigger as a side effect of an ordinary click) - it's
    wired only to the web UI's separate "Recompute scoring multipliers
    (slow, 1-2 min)" checkbox under Advanced refresh
    (`force_scoring_refresh` in `dynasty_core.gather_state`), or to running
    `python scripts/derive_position_multipliers.py` directly, ahead of
    time, to pre-warm the cache before draft day.
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
