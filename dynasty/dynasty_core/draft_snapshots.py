"""Recover which real drop went with each of the user's draft picks, by diffing rosters across refreshes.

Works only when exactly one own pick completed since the last refresh; otherwise the
pick is marked AMBIGUOUS. Not a cache: no TTL, and refresh flags never reset it.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from .constants import CACHE_DIR
from .picks import DraftPickSlot
from .snapshot_io import Migration, load_or_seed, write_if_changed

logger = logging.getLogger(__name__)

AMBIGUOUS = "AMBIGUOUS"

# A finished draft's file stops changing, so an old mtime means the draft is over.
ORPHAN_AGE_DAYS = 90

# How long an `.orphaned` file waits before deletion, so a mistaken mark can be undone
# (Refresh can fire twice in seconds).
ORPHAN_DELETE_COOLDOWN_HOURS = 24

SCHEMA_VERSION = 1
# 0 -> 1: stamping only; the content shape is unchanged.
_MIGRATIONS: dict[int, Migration] = {0: lambda d: d}


def _snapshot_path(draft_id: str) -> Any:
    return CACHE_DIR / f"draft_snapshots_{draft_id}.json"


def _mark_orphaned_snapshots(current_draft_id: str) -> None:
    """Rename snapshot files older than `ORPHAN_AGE_DAYS` (except the current draft) to `.orphaned`.

    Restamps mtime so the deletion cooldown counts from the mark.
    """
    if not CACHE_DIR.exists():
        return
    cutoff = time.time() - ORPHAN_AGE_DAYS * 86400
    current_path = _snapshot_path(current_draft_id)
    for path in CACHE_DIR.glob("draft_snapshots_*.json"):
        if path == current_path:
            continue
        if path.stat().st_mtime >= cutoff:
            continue
        marked_path = path.with_name(path.name + ".orphaned")
        path.rename(marked_path)
        now = time.time()
        os.utime(marked_path, (now, now))
        logger.info("Marked orphaned draft snapshot for future cleanup: %s -> %s", path.name, marked_path.name)


def _delete_orphaned_snapshots() -> None:
    """Delete `.orphaned` files marked at least `ORPHAN_DELETE_COOLDOWN_HOURS` ago. Runs before marking."""
    if not CACHE_DIR.exists():
        return
    cutoff = time.time() - ORPHAN_DELETE_COOLDOWN_HOURS * 3600
    for path in CACHE_DIR.glob("draft_snapshots_*.json.orphaned"):
        if path.stat().st_mtime >= cutoff:
            continue
        path.unlink()
        logger.info("Deleted orphaned draft snapshot: %s", path.name)


def _reconcile(
    snapshot: dict[str, Any],
    own_picks: list[DraftPickSlot],
    current_pick_no: int,
    current_roster_ids: list[str],
    real_picks_by_overall: dict[int, str],
) -> dict[str, Any]:
    """Pure: given the loaded snapshot state, compute the updated one. No disk I/O."""
    own_completed = [p for p in own_picks if p.overall_pick < current_pick_no]
    if snapshot["confirmed_roster"] is None:
        # First sighting of this draft: the current roster is the baseline.
        max_pick = max((p.overall_pick for p in own_completed), default=0)
        return {
            "confirmed_through_pick": max_pick,
            "confirmed_roster": list(current_roster_ids),
            "confirmed_drops": {},
        }

    newly_completed = [p for p in own_completed if p.overall_pick > snapshot["confirmed_through_pick"]]
    if not newly_completed:
        return snapshot

    confirmed_drops = dict(snapshot["confirmed_drops"])
    if len(newly_completed) == 1:
        pick = newly_completed[0]
        picked_id = real_picks_by_overall.get(pick.overall_pick)
        dropped = set(snapshot["confirmed_roster"]) - set(current_roster_ids) - ({picked_id} if picked_id else set())
        if len(dropped) == 1:
            confirmed_drops[str(pick.overall_pick)] = next(iter(dropped))
        elif len(dropped) == 0:
            confirmed_drops[str(pick.overall_pick)] = None
        else:
            confirmed_drops[str(pick.overall_pick)] = AMBIGUOUS
    else:
        # Several own picks since the last refresh: the drops can't be attributed.
        for pick in newly_completed:
            confirmed_drops[str(pick.overall_pick)] = AMBIGUOUS

    return {
        "confirmed_through_pick": newly_completed[-1].overall_pick,
        "confirmed_roster": list(current_roster_ids),
        "confirmed_drops": confirmed_drops,
    }


def reconcile_snapshot(
    draft_id: str,
    own_picks: list[DraftPickSlot],
    current_pick_no: int,
    current_roster_ids: list[str],
    real_picks_by_overall: dict[int, str],
) -> dict[str, Any]:
    """Load, reconcile, persist-if-changed, return the updated snapshot."""
    _delete_orphaned_snapshots()
    _mark_orphaned_snapshots(draft_id)
    path = _snapshot_path(draft_id)
    loaded = load_or_seed(
        path,
        {"confirmed_through_pick": 0, "confirmed_roster": None, "confirmed_drops": {}},
        SCHEMA_VERSION,
        migrations=_MIGRATIONS,
    )
    updated = _reconcile(loaded.content, own_picks, current_pick_no, current_roster_ids, real_picks_by_overall)
    write_if_changed(path, loaded.content, updated, SCHEMA_VERSION, force=loaded.needs_rewrite)
    return updated
