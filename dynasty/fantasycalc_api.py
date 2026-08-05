"""Client for FantasyCalc's public dynasty trade-value rankings.

Used as the player valuation source for dynasty tools in this project — the
project has no valuation model of its own, and FantasyCalc's crowd-sourced
values already cover the current rookie class and join to Sleeper via
`player["sleeperId"]`.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

FANTASYCALC_URL = "https://api.fantasycalc.com/values/current"

CACHE_DIR = Path(__file__).parent / ".cache"
VALUES_CACHE_TTL_SECONDS = 12 * 60 * 60


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


def get_dynasty_values(
    num_qbs: int, num_teams: int, ppr: float, force_refresh: bool = False
) -> list[dict[str, Any]]:
    """Return dynasty trade values for all ranked players, including rookies.

    Args:
        num_qbs: Starting QB-eligible slots (include SUPER_FLEX) — materially
            changes QB value, so this must match the league being evaluated.
        num_teams: League size.
        ppr: Points per reception (0-1).
        force_refresh: Bust the disk cache and re-fetch even if it's fresh.

    Returns:
        Raw FantasyCalc entries, each with a nested `player` dict and a
        `value`. Entries are not necessarily sorted by value.

    Cached to disk (like sleeper_api's players cache) so a plain "Refresh"
    click doesn't re-hit this every time - dynasty market values shift day
    to day, not minute to minute, so a 12h TTL matches players.json's.
    Keyed by (num_qbs, num_teams, ppr) since different league configs need
    different cached values.
    """
    cache_path = CACHE_DIR / f"fantasycalc_values_{num_qbs}_{num_teams}_{ppr}.json"
    if not force_refresh and cache_path.exists():
        age_seconds = time.time() - cache_path.stat().st_mtime
        if age_seconds < VALUES_CACHE_TTL_SECONDS:
            return json.loads(cache_path.read_text(encoding="utf-8"))

    logger.info("Refreshing FantasyCalc dynasty values (numQbs=%s, numTeams=%s, ppr=%s)...", num_qbs, num_teams, ppr)
    params = {
        "isDynasty": "true",
        "numQbs": num_qbs,
        "numTeams": num_teams,
        "ppr": ppr,
    }
    response = _session.get(FANTASYCALC_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    CACHE_DIR.mkdir(exist_ok=True)
    cache_path.write_text(json.dumps(data), encoding="utf-8")
    return data
