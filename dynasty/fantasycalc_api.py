"""Client for FantasyCalc's public dynasty trade values, joined to Sleeper via `player["sleeperId"]`."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests
from cache_dir import CACHE_DIR
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

FANTASYCALC_URL = "https://api.fantasycalc.com/values/current"

VALUES_CACHE_TTL_SECONDS = 12 * 60 * 60


def _build_session() -> requests.Session:
    """A session that retries GETs on connection errors, 429, and 5xx."""
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
    """Return dynasty values for all ranked players, including rookies. Cached 12h per config.

    Args:
        num_qbs: QB-eligible starting slots, including SUPER_FLEX.
        num_teams: League size.
        ppr: Points per reception (0-1).
        force_refresh: Bypass the disk cache.

    Returns:
        Unsorted raw entries, each with a nested `player` dict and a `value`.
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
