"""League-wide rebuild-vs-contend power/timeline read."""

from __future__ import annotations

import logging

import pandas as pd

from .player_pools import roster_fantasy_players
from .roster_needs import positional_strength_summary

logger = logging.getLogger(__name__)


def _weighted_average_age(roster: dict, players: dict[str, dict], fc_by_sleeper_id: dict[str, dict]) -> float | None:
    """Roster age weighted by value, so stars count more than depth. `None` if nothing to weight."""
    weighted_sum = 0.0
    total_weight = 0.0
    for player_id, info in roster_fantasy_players(roster, players):
        age = info.get("age")
        entry = fc_by_sleeper_id.get(player_id)
        adj_value = entry.get("adj_value") if entry else None
        if age is None or not adj_value or adj_value <= 0:
            continue
        weighted_sum += age * adj_value
        total_weight += adj_value
    return weighted_sum / total_weight if total_weight > 0 else None


# Phase cutoffs on power_score. Judgment calls; they now also gate need/drop logic.
PHASE_THRESHOLDS = (-0.3, 0.3)

# Games of shrinkage toward 0.5: at k games the real record gets half weight.
WIN_PCT_SHRINKAGE_K = 4


def _shrunk_win_pct(wins: float, games_played: int, k: int = WIN_PCT_SHRINKAGE_K) -> float:
    """Blend the record toward 0.5 with weight `games / (games + k)`. `wins` counts ties as 0.5."""
    if games_played == 0:
        return 0.5
    weight = games_played / (games_played + k)
    return weight * (wins / games_played) + (1 - weight) * 0.5


def team_power_timeline_scores(
    rosters: list[dict],
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    replacement_level: dict[str, float],
    league: dict,
) -> pd.DataFrame:
    """Rebuild-vs-contend read for every team, indexed by roster_id.

    `power_score` is the mean of league z-scores (ddof=0) for `aggregate_vor`,
    `weighted_age`, and `win_pct_shrunk`. `win_pct` is the real record, for display only.
    `quality_score` (strength + record) and `timeline_score` (age) are also exposed.
    `phase` and `rank` derive from `power_score`.
    """
    roster_positions = league["roster_positions"]

    rows = []
    for roster in rosters:
        strength = positional_strength_summary(
            roster, players, fc_by_sleeper_id, replacement_level, roster_positions
        )
        settings = roster.get("settings") or {}
        wins, losses, ties = settings.get("wins", 0), settings.get("losses", 0), settings.get("ties", 0)
        games_played = wins + losses + ties
        effective_wins = wins + 0.5 * ties
        rows.append(
            {
                "roster_id": roster["roster_id"],
                "aggregate_vor": strength["vor"].sum(),
                "weighted_age": _weighted_average_age(roster, players, fc_by_sleeper_id),
                # Display only.
                "win_pct": effective_wins / games_played if games_played > 0 else 0.5,
                # Feeds the z-score only; never display as "Win %".
                "win_pct_shrunk": _shrunk_win_pct(effective_wins, games_played),
                # Distinguishes a real record from the preseason default.
                "games_played": games_played,
            }
        )
    scores = pd.DataFrame(rows).set_index("roster_id")
    missing_age = scores["weighted_age"].isna()
    if missing_age.any():
        logger.warning("No valued players with a known age on rosters %s; using league mean age", list(scores.index[missing_age]))
    scores["weighted_age"] = scores["weighted_age"].fillna(scores["weighted_age"].mean())

    def _z(series: pd.Series) -> pd.Series:
        std = series.std(ddof=0)
        return (series - series.mean()) / std if std else pd.Series(0.0, index=series.index)

    vor_z, age_z, win_z = _z(scores["aggregate_vor"]), _z(scores["weighted_age"]), _z(scores["win_pct_shrunk"])
    scores["power_score"] = (vor_z + age_z + win_z) / 3
    scores["quality_score"] = (vor_z + win_z) / 2
    scores["timeline_score"] = age_z
    scores["phase"] = pd.cut(
        scores["power_score"],
        bins=[-float("inf"), PHASE_THRESHOLDS[0], PHASE_THRESHOLDS[1], float("inf")],
        labels=["rebuilding", "treading_water", "contending"],
    )
    scores["rank"] = scores["power_score"].rank(ascending=False, method="min").astype(int)
    return scores.round(2)
