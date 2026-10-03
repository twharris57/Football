"""Per-player status flags and roster-value/aging analysis."""

from __future__ import annotations

import pandas as pd

from .player_pools import roster_fantasy_players

# RBs age out earliest, QBs latest. Judgment calls; tune by feel.
LOW_VALUE_AGING_AGE = {"RB": 27, "WR": 29, "TE": 30, "QB": 33}
DEFAULT_LOW_VALUE_AGING_AGE = 29
LOW_VALUE_YOUNG_AGE = 24

# Expansions for Sleeper's cryptic injury codes; plain words pass through.
INJURY_STATUS_DESCRIPTIONS = {
    "PUP": "Physically Unable to Perform",
    "COV": "COVID-19",
    "Sus": "Suspended",
    "NA": "Not Active",
    "DNR": "Did Not Report",
    "IR": "Injured Reserve",
}


def player_status_details(
    player_id: str, info: dict, taxi_ids: set[str], reserve_ids: set[str]
) -> list[tuple[str, str]]:
    """`(icon, description)` pairs: rookie, injured, taxi, IR. A player can have several."""
    details: list[tuple[str, str]] = []
    if not info.get("years_exp"):
        details.append(("🆕", "Rookie (no NFL experience yet)"))
    injury_status = info.get("injury_status")
    if injury_status:
        details.append(("🏥", INJURY_STATUS_DESCRIPTIONS.get(injury_status, injury_status)))
    if player_id in taxi_ids:
        details.append(("🌱", "Taxi squad"))
    if player_id in reserve_ids:
        details.append(("🩹", "IR / Reserve"))
    return details


def player_status_flags(player_id: str, info: dict, taxi_ids: set[str], reserve_ids: set[str]) -> str:
    """Compact icon-only summary of player_status_details, as a single string."""
    return " ".join(icon for icon, _description in player_status_details(player_id, info, taxi_ids, reserve_ids))


def roster_value_analysis(
    roster: dict,
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    byes: dict[str, int] | None = None,
    phase: str = "rebuilding",
) -> pd.DataFrame:
    """Roster sorted by `adj_value`, lowest first, with drop-candidate notes.

    The bottom quartile (min 3) is low-value. `note` holds young low-value players while
    rebuilding and flags aging ones (per-position `LOW_VALUE_AGING_AGE`).
    """
    byes = byes or {}
    taxi_ids = set(roster.get("taxi") or [])
    reserve_ids = set(roster.get("reserve") or [])

    rows = []
    for player_id, info in roster_fantasy_players(roster, players):
        position = info.get("position")
        fc_entry = fc_by_sleeper_id.get(player_id)
        value = fc_entry["value"] if fc_entry else None
        team = info.get("team")
        rows.append(
            {
                "name": info.get("full_name"),
                "pos": position,
                "age": info.get("age"),
                "years_exp": info.get("years_exp"),
                "status": player_status_flags(player_id, info, taxi_ids, reserve_ids),
                "status_details": player_status_details(player_id, info, taxi_ids, reserve_ids),
                "bye": byes.get(team) if team else None,
                "value": value,
                "adj_value": fc_entry.get("adj_value") if fc_entry else None,
            }
        )

    roster_df = pd.DataFrame(rows)
    if roster_df.empty:
        return roster_df

    roster_df = roster_df.sort_values("adj_value", ascending=True, na_position="first").reset_index(drop=True)
    low_value_cutoff = max(3, len(roster_df) // 4)
    is_low_value = roster_df.index < low_value_cutoff

    def note(low_value: bool, age: float | None, position: str | None) -> str:
        if not low_value:
            return ""
        if phase == "rebuilding" and age is not None and age < LOW_VALUE_YOUNG_AGE:
            return "Low value, young — rebuild upside, hold"
        aging_age = LOW_VALUE_AGING_AGE.get(position, DEFAULT_LOW_VALUE_AGING_AGE) if position else DEFAULT_LOW_VALUE_AGING_AGE
        if age is not None and age >= aging_age:
            return "Low value, aging — drop candidate"
        return "Low value — monitor"

    roster_df["note"] = [
        note(lv, age, pos) for lv, age, pos in zip(is_low_value, roster_df["age"], roster_df["pos"])
    ]
    return roster_df
