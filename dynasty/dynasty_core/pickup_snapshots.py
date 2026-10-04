"""Track players' NFL team, depth-chart order, and status across refreshes to flag pickups.

Only improvements count (a new team, moving up the depth chart, becoming Active). The
whole teamed population is tracked, not just free agents, so a fantasy drop doesn't
look like a signing. Callers filter changes to the free-agent pool.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .constants import CACHE_DIR
from .snapshot_io import Migration, load_or_seed, write_if_changed

_TRACKED_FIELDS = ("team", "depth_chart_order", "status")

SCHEMA_VERSION = 1
# 0 -> 1: stamping only; the content shape is unchanged.
_MIGRATIONS: dict[int, Migration] = {0: lambda d: d}


def _snapshot_path(league_id: str, season: str) -> Path:
    return CACHE_DIR / f"pickup_snapshots_{league_id}_{season}.json"


def _diff(previous_players: dict[str, dict], universe: dict[str, dict]) -> list[dict[str, Any]]:
    """Changes since `previous_players`. Pure.

    A player with no prior entry is reported as a new signing (`kind="team"`, `old=None`).
    """
    changes = []
    for player_id, info in universe.items():
        prior = previous_players.get(player_id)
        team = info.get("team")
        depth_chart_order = info.get("depth_chart_order")
        status = info.get("status")

        if prior is None:
            changes.append({"player_id": player_id, "kind": "team", "old": None, "new": team})
            continue

        if team != prior.get("team"):
            changes.append({"player_id": player_id, "kind": "team", "old": prior.get("team"), "new": team})

        prior_order = prior.get("depth_chart_order")
        if depth_chart_order is not None and prior_order is not None and depth_chart_order < prior_order:
            changes.append({"player_id": player_id, "kind": "depth_chart", "old": prior_order, "new": depth_chart_order})

        prior_status = prior.get("status")
        if status == "Active" and prior_status is not None and prior_status != "Active":
            changes.append({"player_id": player_id, "kind": "status", "old": prior_status, "new": status})

    return changes


def reconcile_pickup_snapshot(
    league_id: str, season: str, universe: dict[str, dict]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load, diff, save if changed; returns `(snapshot, changes)`.

    Keyed by league and season. Entries are merged, so a player who leaves the population
    keeps their last-known values.
    """
    path = _snapshot_path(league_id, season)
    loaded = load_or_seed(path, {"initialized": False, "players": {}}, SCHEMA_VERSION, migrations=_MIGRATIONS)
    existing = loaded.content

    current_players = {
        player_id: {field: info.get(field) for field in _TRACKED_FIELDS} for player_id, info in universe.items()
    }

    if existing["initialized"]:
        changes = _diff(existing["players"], universe)
    else:
        # First run for this league/season: record a baseline, report nothing.
        changes = []

    updated = {"initialized": True, "players": {**existing["players"], **current_players}}
    write_if_changed(path, existing, updated, SCHEMA_VERSION, force=loaded.needs_rewrite)
    return updated, changes
