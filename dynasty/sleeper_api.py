"""Thin client for Sleeper's public, read-only API, with disk caching for slow-changing data."""

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

BASE_URL = "https://api.sleeper.app/v1"
PLAYERS_CACHE_PATH = CACHE_DIR / "players.json"
PLAYERS_CACHE_TTL_SECONDS = 12 * 60 * 60
TRANSACTIONS_CACHE_TTL_SECONDS = 12 * 60 * 60
PROJECTIONS_CACHE_TTL_SECONDS = 60 * 60


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


def _get(path: str) -> Any:
    """Fetch and parse a JSON response from the Sleeper API."""
    response = _session.get(f"{BASE_URL}{path}", timeout=30)
    response.raise_for_status()
    return response.json()


def get_league(league_id: str) -> dict[str, Any]:
    """Return league settings, scoring, and metadata."""
    return _get(f"/league/{league_id}")


def get_rosters(league_id: str) -> list[dict[str, Any]]:
    """Return every roster in the league."""
    return _get(f"/league/{league_id}/rosters")


def get_users(league_id: str) -> list[dict[str, Any]]:
    """Return every team owner in the league."""
    return _get(f"/league/{league_id}/users")


def get_draft(draft_id: str) -> dict[str, Any]:
    """Return draft settings, pick order, and slot-to-roster mapping."""
    return _get(f"/draft/{draft_id}")


def get_draft_picks(draft_id: str) -> list[dict[str, Any]]:
    """Return picks made so far in the draft, in pick order."""
    return _get(f"/draft/{draft_id}/picks")


def get_traded_picks(league_id: str) -> list[dict[str, Any]]:
    """Return every future draft pick that has changed hands via trade."""
    return _get(f"/league/{league_id}/traded_picks")


def get_transactions(league_id: str, season: str, current_leg: int, force_refresh: bool = False) -> list[dict[str, Any]]:
    """Every transaction for legs 1..current_leg. Cached 12h.

    Waiver bids are in `settings.waiver_bid`; `status == "complete"` means the bid won.
    """
    cache_path = CACHE_DIR / f"transactions_{league_id}_{season}.json"
    if not force_refresh and cache_path.exists():
        age_seconds = time.time() - cache_path.stat().st_mtime
        if age_seconds < TRANSACTIONS_CACHE_TTL_SECONDS:
            return json.loads(cache_path.read_text(encoding="utf-8"))

    logger.info("Refreshing transaction history from Sleeper (legs 1-%d)...", current_leg)
    transactions: list[dict[str, Any]] = []
    for leg in range(1, current_leg + 1):
        transactions.extend(_get(f"/league/{league_id}/transactions/{leg}"))

    CACHE_DIR.mkdir(exist_ok=True)
    cache_path.write_text(json.dumps(transactions), encoding="utf-8")
    return transactions


def get_weekly_projections(season: str, week: int, force_refresh: bool = False) -> dict[str, dict[str, float]]:
    """This week's per-player stat projections, keyed by player_id.

    Undocumented endpoint, shared across leagues, using the same stat keys as
    `scoring_settings`. Short cache TTL because projections move during the week.
    """
    cache_path = CACHE_DIR / f"projections_{season}_{week}.json"
    if not force_refresh and cache_path.exists():
        age_seconds = time.time() - cache_path.stat().st_mtime
        if age_seconds < PROJECTIONS_CACHE_TTL_SECONDS:
            return json.loads(cache_path.read_text(encoding="utf-8"))

    logger.info("Refreshing weekly projections from Sleeper (season %s, week %d)...", season, week)
    data = _get(f"/projections/nfl/regular/{season}/{week}")

    CACHE_DIR.mkdir(exist_ok=True)
    cache_path.write_text(json.dumps(data), encoding="utf-8")
    return data


def get_players(force_refresh: bool = False) -> dict[str, Any]:
    """Return the full NFL player dataset (~14MB), keyed by player_id. Cached on disk."""
    if not force_refresh and PLAYERS_CACHE_PATH.exists():
        age_seconds = time.time() - PLAYERS_CACHE_PATH.stat().st_mtime
        if age_seconds < PLAYERS_CACHE_TTL_SECONDS:
            return json.loads(PLAYERS_CACHE_PATH.read_text(encoding="utf-8"))

    logger.info("Refreshing players cache from Sleeper (~14MB)...")
    data = _get("/players/nfl")
    CACHE_DIR.mkdir(exist_ok=True)
    PLAYERS_CACHE_PATH.write_text(json.dumps(data), encoding="utf-8")
    return data
