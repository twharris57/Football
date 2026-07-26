"""Client for FantasyCalc's public dynasty trade-value rankings.

Used as the player valuation source for dynasty tools in this project — the
project has no valuation model of its own, and FantasyCalc's crowd-sourced
values already cover the current rookie class and join to Sleeper via
`player["sleeperId"]`.
"""

from __future__ import annotations

from typing import Any

import requests

FANTASYCALC_URL = "https://api.fantasycalc.com/values/current"


def get_dynasty_values(num_qbs: int, num_teams: int, ppr: float) -> list[dict[str, Any]]:
    """Return dynasty trade values for all ranked players, including rookies.

    Args:
        num_qbs: Starting QB-eligible slots (include SUPER_FLEX) — materially
            changes QB value, so this must match the league being evaluated.
        num_teams: League size.
        ppr: Points per reception (0-1).

    Returns:
        Raw FantasyCalc entries, each with a nested `player` dict and a
        `value`. Entries are not necessarily sorted by value.
    """
    params = {
        "isDynasty": "true",
        "numQbs": num_qbs,
        "numTeams": num_teams,
        "ppr": ppr,
    }
    response = requests.get(FANTASYCALC_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.json()
