"""League-wide, one-row-per-team summary (League tab)."""

from __future__ import annotations

import pandas as pd

from .lineup import roster_capacity
from .roster_needs import positional_strength_summary
from .roster_value import roster_value_analysis


def league_team_summaries(
    rosters_by_id: dict[int, dict],
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    byes: dict[str, int],
    league: dict,
    replacement_level: dict[str, float],
    team_names: dict[int, str],
    team_power_timeline: pd.DataFrame,
) -> pd.DataFrame:
    """One row per team: total value, biggest need (lowest `vor`), capacity, power read.

    Uses only cheap per-roster primitives — `team_roster_analysis()` per team would
    run the free-agent board ~12 times per refresh.
    """
    roster_positions = league["roster_positions"]
    rows = []
    for roster_id, roster in rosters_by_id.items():
        value_df = roster_value_analysis(roster, players, fc_by_sleeper_id, byes)
        total_value = float(value_df["adj_value"].sum()) if not value_df.empty else 0.0

        strength = positional_strength_summary(roster, players, fc_by_sleeper_id, replacement_level, roster_positions)
        biggest_need = strength["vor"].idxmin()

        capacity = roster_capacity(roster, league)

        rows.append(
            {
                "roster_id": roster_id,
                "team": team_names.get(roster_id, f"Roster {roster_id}"),
                "total_value": total_value,
                "biggest_need": biggest_need,
                "active_open": capacity["active_open"],
                "taxi_open": capacity["taxi_open"],
            }
        )

    summary = pd.DataFrame(rows).set_index("roster_id")
    summary = summary.join(team_power_timeline[["phase", "rank", "win_pct", "games_played"]])
    return summary.round(1)
