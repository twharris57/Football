"""Shared synthetic-data builders for dynasty_core package tests.

Everything here uses synthetic players/league/values, never a real Sleeper
or FantasyCalc call — per testing.md ("mock only external services you do
not control"), but these are pure functions over plain data structures, so
there's nothing to mock in the first place, just data to construct.
"""

from __future__ import annotations

import pandas as pd

SIMPLE_LEAGUE = {
    "roster_positions": ["QB", "RB", "WR", "FLEX", "SUPER_FLEX", "BN", "BN"],
    "settings": {"taxi_slots": 2},
}

# find_trade_offers() always builds a pick pool from a pick-value table, even
# when a test's scenario doesn't involve any picks - an empty table with the
# right columns keeps those tests from needing to fabricate irrelevant rows.
EMPTY_PICKS = pd.DataFrame(columns=["pick", "owner", "owner_roster_id", "value"])


def make_player(position: str, team: str = "AAA", full_name: str | None = None) -> dict:
    return {"position": position, "team": team, "full_name": full_name or f"{position}-{team}"}


def fc_entry(sleeper_id: str, value: float, tier: int = 1, position: str | None = None) -> dict:
    return {"player": {"sleeperId": sleeper_id, "position": position}, "value": value, "maybeTier": tier}
