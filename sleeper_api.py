"""Thin client for Sleeper's public, read-only fantasy football API.

Caches the large players reference dataset locally since it changes only a
few times a day and is unnecessary to re-download on every draft refresh.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.sleeper.app/v1"
CACHE_DIR = Path(__file__).parent / ".cache"
PLAYERS_CACHE_PATH = CACHE_DIR / "players.json"
PLAYERS_CACHE_TTL_SECONDS = 12 * 60 * 60


def _get(path: str) -> Any:
    """Fetch and parse a JSON response from the Sleeper API."""
    response = requests.get(f"{BASE_URL}{path}", timeout=30)
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


def get_players(force_refresh: bool = False) -> dict[str, Any]:
    """Return the full NFL player reference dataset, keyed by player_id.

    This endpoint is ~14MB and changes only a few times a day, so results
    are cached to disk and reused until PLAYERS_CACHE_TTL_SECONDS elapses.
    """
    if not force_refresh and PLAYERS_CACHE_PATH.exists():
        age_seconds = time.time() - PLAYERS_CACHE_PATH.stat().st_mtime
        if age_seconds < PLAYERS_CACHE_TTL_SECONDS:
            return json.loads(PLAYERS_CACHE_PATH.read_text(encoding="utf-8"))

    logger.info("Refreshing players cache from Sleeper (~14MB)...")
    data = _get("/players/nfl")
    CACHE_DIR.mkdir(exist_ok=True)
    PLAYERS_CACHE_PATH.write_text(json.dumps(data), encoding="utf-8")
    return data
