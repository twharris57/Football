"""Per-player real-scoring recompute (see PROJECT_PLAN.md, valuation step B).

FantasyCalc's dynasty values are generated under an assumed scoring model
that doesn't match this league's real `scoring_settings` (6pt passing TDs,
a TE reception premium, a -3 INT penalty instead of the usual -2, first-down
and long-play bonuses, and whatever passing/rushing/receiving yardage rates
this league actually uses). FantasyCalc's API only lets us tune `numQbs`,
`numTeams`, and `ppr` — nothing else — so the rest of the mismatch has to be
corrected after the fact.

This module computes, for every player with enough real NFL volume to
trust it, a personalized correction ratio: their own points recomputed
under this league's *actual* scoring_settings, divided by their points
under FantasyCalc's assumed baseline model (see BASELINE_SCORING below —
an explicit, documented assumption, since FantasyCalc doesn't publish its
formula). Players without enough volume (rookies, backups, or veterans
below the qualifying bar) fall back to a position-average ratio, computed
from that same pooled qualifying sample.

Deliberately independent of dynasty_core.py (no import of it) to avoid a
circular import - dynasty_core.py imports this module to call
get_multipliers(), so this module can't import dynasty_core back.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import nfl_data_py as nfl
import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / ".cache"
MULTIPLIERS_CACHE_PATH = CACHE_DIR / "scoring_multipliers.json"

LOOKBACK_SEASONS = 3

# Minimum season volume to trust a player's own recomputed ratio rather than
# falling back to the position average - same spirit as step E's QB/TE bars
# (a "meaningful starter" season), extended here to RB/WR since first-down
# and long-play bonuses apply to them too, not just QB/TE.
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


def _gsis_to_sleeper() -> dict[str, str]:
    ids = nfl.import_ids().dropna(subset=["gsis_id", "sleeper_id"])
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

    gsis_to_sleeper = _gsis_to_sleeper()

    per_player: dict[str, float] = {}
    position_average: dict[str, float] = {}
    for position, (volume_col, min_volume) in QUALIFYING_VOLUME.items():
        qualifying = season_totals[
            (season_totals["position"] == position) & (season_totals[volume_col] >= min_volume)
        ]
        if qualifying.empty:
            continue
        pos_ratio = _sane_ratio(qualifying["real_points"].sum(), qualifying["baseline_points"].sum())
        if pos_ratio is not None:
            position_average[position] = pos_ratio

        for player_id, group in qualifying.groupby("player_id"):
            ratio = _sane_ratio(group["real_points"].sum(), group["baseline_points"].sum())
            if ratio is None:
                continue
            sleeper_id = gsis_to_sleeper.get(player_id)
            if sleeper_id is None:
                continue
            per_player[sleeper_id] = ratio

    return {"seasons": seasons, "per_player": per_player, "position_average": position_average}


def get_multipliers(scoring_settings: dict[str, float], current_season: str, force_refresh: bool = False) -> dict[str, Any]:
    """Return {"seasons": [...], "per_player": {sleeper_id: ratio}, "position_average": {pos: ratio}}.

    Cached to disk with no TTL, unlike sleeper_api's players cache - the
    underlying data is entirely historical/complete seasons, so nothing
    changes between refreshes except once a year when a new season's stats
    are published. `dynasty_core.gather_state` deliberately never passes
    `force_refresh=True` here (a 1-2 minute synchronous pull, unsuitable to
    trigger live mid-draft) - the only way this recomputes is running
    `python scripts/derive_position_multipliers.py` directly, ahead of time,
    to pre-warm the cache before draft day.
    """
    if not force_refresh and MULTIPLIERS_CACHE_PATH.exists():
        cached = json.loads(MULTIPLIERS_CACHE_PATH.read_text(encoding="utf-8"))
        return {"seasons": cached["seasons"], "per_player": cached["per_player"], "position_average": cached["position_average"]}

    logger.info("Recomputing real-scoring multipliers from nfl_data_py (weekly + play-by-play)...")
    result = _derive_multipliers(scoring_settings, current_season)

    CACHE_DIR.mkdir(exist_ok=True)
    MULTIPLIERS_CACHE_PATH.write_text(
        json.dumps({**result, "computed_at": time.time()}),
        encoding="utf-8",
    )
    return result
