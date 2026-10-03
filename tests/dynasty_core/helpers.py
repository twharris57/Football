"""Synthetic data builders for dynasty_core tests."""

from __future__ import annotations

import pandas as pd

SIMPLE_LEAGUE = {
    "roster_positions": ["QB", "RB", "WR", "FLEX", "SUPER_FLEX", "BN", "BN"],
    "settings": {"taxi_slots": 2},
}

# An empty pick-value table for tests that don't involve picks.
EMPTY_PICKS = pd.DataFrame(columns=["pick", "owner", "owner_roster_id", "value"])


def make_player(position: str, team: str = "AAA", full_name: str | None = None) -> dict:
    return {"position": position, "team": team, "full_name": full_name or f"{position}-{team}"}


def fc_entry(sleeper_id: str, value: float, tier: int = 1, position: str | None = None) -> dict:
    return {"player": {"sleeperId": sleeper_id, "position": position}, "value": value, "maybeTier": tier}
