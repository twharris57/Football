"""League-wide rebuild-vs-contend power/timeline read."""

from __future__ import annotations

import pandas as pd

from .player_pools import roster_fantasy_players
from .roster_needs import positional_strength_summary


def _weighted_average_age(roster: dict, players: dict[str, dict], fc_by_sleeper_id: dict[str, dict]) -> float | None:
    """Value-weighted average age across a roster's fantasy-relevant players.

    An older, more *valuable* roster should skew a timeline read toward
    win-now more than a flat average would - a bench full of unproven
    22-year-olds shouldn't outweigh a 27-year-old franchise piece the way a
    plain mean age treats them equally. Returns None if no player has both
    a known age and a positive value (nothing to weight).
    """
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


# z-score cutoffs on the continuous power_score for the phase label - a
# judgment call to revisit by feel (see valuation_principles.md), not a
# derived constant. Originally display-only, tolerant of an imprecise
# boundary since a human just read the label - roster_needs.py's
# phase-aware need/note switch and the draft plan's "flagged need"
# reasoning now branch on this same boundary too, so its calibration has
# real behavioral stakes, not just a label choice. See
# PROJECT_PLAN_DYNASTY.md's RT-30 for the open question of whether it
# still holds up under that heavier use.
PHASE_THRESHOLDS = (-0.3, 0.3)

# Games worth of shrinkage weight toward a neutral 0.5 prior - a judgment
# call (see valuation_principles.md), not derived. At WIN_PCT_SHRINKAGE_K
# games played, win_pct gets exactly half its raw weight; by ~3x this many
# games the shrinkage is mostly faded. Low enough that a real mid-season
# record still dominates, high enough that a 1-0 start doesn't swing the
# z-score as hard as a 10-0 finish does.
WIN_PCT_SHRINKAGE_K = 4


def _shrunk_win_pct(wins: int, games_played: int, k: int = WIN_PCT_SHRINKAGE_K) -> float:
    """Blend actual win_pct toward neutral 0.5, weighted by how many games have resolved.

    Reduces to the existing zero-games neutral 0.5 default exactly when
    games_played == 0. Weight on the real record grows as
    games_played / (games_played + k), so early results count
    proportionally to how much they've actually resolved instead of
    getting full weight after a single game.
    """
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
    """Continuous rebuild-vs-contend read for every team in the league, indexed by roster_id.

    Combines three signals — `aggregate_vor` (roster strength),
    `weighted_age` (timeline direction), `win_pct_shrunk` (actual record,
    neutral `0.5` pre-season and shrunk toward it early in the season via
    `_shrunk_win_pct`, so a 1-0/0-1 start doesn't swing the score as hard as
    a settled record does) — each z-scored across the league (population
    std, `ddof=0`) and averaged into `power_score`. The raw, unshrunk
    `win_pct` is exposed separately for display (`streamlit_app.py` prints
    it verbatim next to a literal "Win %" label,
    which must show the real record, not the statistical prior fed to the
    score — see `valuation_principles.md`'s "a field used as both an
    internal score input and a user-facing label needs two names" rule).
    `quality_score` (strength + record) and `timeline_score` (age alone)
    are also exposed separately, since blending both axes into one number
    can hide a strong/young team and a weak/old team landing on the same
    score. `phase` and `rank` are display-only derivatives of
    `power_score`; `games_played` lets a UI distinguish a real record from
    the neutral pre-season default. Recomputed fresh every call from
    already-pulled data, never cached. Full methodology and rationale for
    each design choice in docs/rookie-draft-big-board.md's "Team timeline /
    power-timeline read" section.
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
        rows.append(
            {
                "roster_id": roster["roster_id"],
                "aggregate_vor": strength["vor"].sum(),
                "weighted_age": _weighted_average_age(roster, players, fc_by_sleeper_id),
                # Raw record for display - never fed to the z-scoring below.
                "win_pct": wins / games_played if games_played > 0 else 0.5,
                # Small-sample-shrunk record for power_score's z-scoring only
                # - must never be printed as-is next to a "Win %" label.
                "win_pct_shrunk": _shrunk_win_pct(wins, games_played),
                # Exposed so a UI can tell "this team's win_pct is a real
                # record" from "nobody's played yet, this is the neutral
                # default" - the z-scored win_pct alone can't distinguish
                # those (see the class docstring's "emergent property" note).
                "games_played": games_played,
            }
        )
    scores = pd.DataFrame(rows).set_index("roster_id")
    # A team with no player carrying both a known age and a positive value
    # (never observed in practice, but not impossible for an empty/near-empty
    # roster) falls back to the league's mean age instead of dropping out of
    # the z-score entirely.
    scores["weighted_age"] = scores["weighted_age"].fillna(scores["weighted_age"].mean())

    def _z(series: pd.Series) -> pd.Series:
        std = series.std(ddof=0)
        return (series - series.mean()) / std if std else pd.Series(0.0, index=series.index)

    vor_z, age_z, win_z = _z(scores["aggregate_vor"]), _z(scores["weighted_age"]), _z(scores["win_pct_shrunk"])
    scores["power_score"] = (vor_z + age_z + win_z) / 3
    # Split out for consumers that need "how good" and "which way pointed"
    # kept apart rather than blended - see the class docstring.
    scores["quality_score"] = (vor_z + win_z) / 2
    scores["timeline_score"] = age_z
    scores["phase"] = pd.cut(
        scores["power_score"],
        bins=[-float("inf"), PHASE_THRESHOLDS[0], PHASE_THRESHOLDS[1], float("inf")],
        labels=["rebuilding", "treading_water", "contending"],
    )
    # Rank 1 = strongest power_score in the league - a plain "N of league
    # size" beats asking a user to interpret a raw z-scored number cold.
    scores["rank"] = scores["power_score"].rank(ascending=False, method="min").astype(int)
    return scores.round(2)
