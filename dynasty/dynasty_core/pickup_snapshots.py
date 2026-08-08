"""Persist fantasy-relevant NFL players' team/depth-chart/status across refreshes to
detect in-season pickup opportunities week-over-week.

`free_agent_board()` is a real-time snapshot recomputed fresh every refresh, like
everything else in this project - nothing compares this refresh against the last one.
This module adds exactly that comparison for three signals already present in
Sleeper's own player data (no new fetch): `team` (signing with a real NFL team),
`depth_chart_order` (a lower number is better - closer to starting), and `status`
(transitioning to "Active"). Only improvements are flagged for the latter two - a
demotion isn't a pickup opportunity.

Tracks `fantasy_relevant_teamed_players()`'s full population - every fantasy-relevant
player with a real NFL team, not just the current free-agent subset - deliberately.
A player can enter the free-agent *pool* for reasons that have nothing to do with an
NFL-team change (a fantasy manager drops them), and tracking only the pool would make
that look identical to a real first-time signing the moment they reappear. Tracking
the broader population means a player who was rostered by a fantasy team the whole
time already has a real prior entry on file, so a fantasy-roster-only event correctly
produces no "team" change. See
`.claude/conventions/valuation_principles.md`'s "first time seen in this narrower
pool" rule. Alerting still only makes sense for players who are actually available -
callers should filter `changes` down to the current free-agent pool before acting on
them; this module has no notion of "pool" at all, only "population being tracked."

Deliberately not TTL-based and independent of force_full_refresh, same rationale as
draft_snapshots.py: this is accumulated cross-refresh state, not a freshness cache.
Shares its load/write shell with draft_snapshots.py via snapshot_io.py; the diff logic
itself is separate since a roster-membership diff and an attribute diff don't
generalize to the same function.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .constants import CACHE_DIR
from .snapshot_io import load_or_seed, write_if_changed

_TRACKED_FIELDS = ("team", "depth_chart_order", "status")


def _snapshot_path(league_id: str, season: str) -> Path:
    return CACHE_DIR / f"pickup_snapshots_{league_id}_{season}.json"


def _diff(previous_players: dict[str, dict], universe: dict[str, dict]) -> list[dict[str, Any]]:
    """Pure: compare each tracked player's current team/depth_chart_order/status
    against their last-known values. No disk I/O.

    A player with no entry in `previous_players` is treated as a real "just
    signed with a team" event (kind "team", old=None) - not skipped. Skipping
    would silently and permanently miss this feature's headline scenario (a
    player signing with a team for the first time), since there's no later
    point where they'd suddenly acquire a "prior entry" to compare against.
    This is only a safe reading of "first entry" because `universe` is the
    full fantasy-relevant/teamed population (see module docstring), not just
    the free-agent subset - a player merely dropped by a fantasy manager
    while staying on the same NFL roster already has a real prior entry here,
    so they hit the team/depth_chart/status comparisons below instead of
    this branch. The true first-ever-run case (nothing has ever been tracked
    at all) is handled one level up, in reconcile_pickup_snapshot, before
    this is called.
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
    """Load, diff, persist-if-changed, return (updated_snapshot, changes).

    `universe` is typically `fantasy_relevant_teamed_players()`'s output -
    deliberately broader than the free-agent pool alone (see module
    docstring). Keyed by `league_id` and `season` together -
    draft_snapshots.py gets season-rollover safety for free from draft_id
    changing every year automatically; whether Sleeper's league_id itself
    rotates per season for a continuing dynasty league wasn't verified
    against this project's own data, so the season suffix is a cheap hedge
    either way, not a real cost.

    Snapshot entries are merged, not replaced: a player who leaves the
    tracked population (no longer has a real NFL team) keeps their
    last-known values on file, so a real change is still detectable if/when
    they re-enter later rather than silently resetting to "first sighting"
    again.
    """
    path = _snapshot_path(league_id, season)
    existing = load_or_seed(path, {"initialized": False, "players": {}})

    current_players = {
        player_id: {field: info.get(field) for field in _TRACKED_FIELDS} for player_id, info in universe.items()
    }

    if existing["initialized"]:
        changes = _diff(existing["players"], universe)
    else:
        # True first-ever run for this league/season: baseline only, no
        # changes reported - mirrors draft_snapshots.py's
        # confirmed_roster-is-None baseline case.
        changes = []

    updated = {"initialized": True, "players": {**existing["players"], **current_players}}
    write_if_changed(path, existing, updated)
    return updated, changes
