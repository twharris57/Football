"""Client for FantasyCalc's public dynasty trade-value rankings.

Used as the player valuation source for dynasty tools in this project — the
project has no valuation model of its own, and FantasyCalc's crowd-sourced
values already cover the current rookie class and join to Sleeper via
`player["sleeperId"]`.
"""

from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

FANTASYCALC_URL = "https://api.fantasycalc.com/values/current"


def _build_session() -> requests.Session:
    """A session that retries transient failures (connection errors, 5xx, 429).

    Draft day means everyone hits this API at once — a bare `requests.get`
    with no retry turns one transient hiccup into a hard failure for
    whoever hit it, mid-draft. Only GET is used here, so retrying is safe
    (no risk of double-submitting a write).
    """
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_session = _build_session()


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
    response = _session.get(FANTASYCALC_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.json()
