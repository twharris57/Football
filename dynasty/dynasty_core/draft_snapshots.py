"""Persist real roster state across refreshes to attribute draft-plan drops to a specific pick.

Sleeper adds a drafted player straight to the team's roster the moment the
pick is made, so the live roster already reflects every pick made so far on
any refresh (confirmed via sleeper_api.py usage elsewhere in this project).
That means a real drop is recoverable by diffing the roster before/after a
newly-completed pick - but only when exactly one of the user's own picks
completed since the last refresh. If two or more complete in the same gap,
the diff can't tell which drop paired with which pick, so that gap is marked
"AMBIGUOUS" rather than guessed at.

Deliberately not TTL-based - the closest existing precedent is
player_scoring.get_multipliers() (no TTL, only overwritten by an explicit
condition), the only other non-refetch-if-stale cache in this project - and
deliberately independent of force_full_refresh/force_scoring_refresh, since
those are about market-data freshness and shouldn't silently wipe this
mid-draft. Once a season's draft is over, its file is simply never read
again (next season gets a new draft_id from Sleeper) - see
_mark_orphaned_snapshots/_delete_orphaned_snapshots for how those old
files are marked and eventually removed.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .constants import CACHE_DIR
from .picks import DraftPickSlot
from .snapshot_io import Migration, load_or_seed, write_if_changed

logger = logging.getLogger(__name__)

AMBIGUOUS = "AMBIGUOUS"

# A draft's own snapshot file stops being written to the moment the draft
# ends (write_if_changed no-ops once _reconcile finds nothing new), so its
# mtime freezes at roughly end-of-draft - a reasonable proxy for "this
# draft is over" without needing this module to track every draft_id a
# league has ever used. 90 days comfortably clears a full rookie draft plus
# any reasonable post-draft review window before a file is considered
# orphaned.
ORPHAN_AGE_DAYS = 90

SCHEMA_VERSION = 1
# 0 -> 1: adopting explicit schema_version stamping via snapshot_io.py -
# the business shape itself isn't changing in this migration, only the
# stamp is being introduced, but it must still be registered or
# load_or_seed refuses to read every real file already on disk (all of
# them predate this mechanism and are implicitly version 0).
_MIGRATIONS: dict[int, Migration] = {0: lambda d: d}


def _snapshot_path(draft_id: str) -> Any:
    return CACHE_DIR / f"draft_snapshots_{draft_id}.json"


def _mark_orphaned_snapshots(current_draft_id: str) -> None:
    """Rename old draft_snapshots_*.json files that look orphaned - older
    than ORPHAN_AGE_DAYS and not the draft currently being reconciled - by
    appending an `.orphaned` suffix.

    A soft, reversible marking step, not deletion itself - actual removal
    is `_delete_orphaned_snapshots()`'s job, called before this one on
    every `reconcile_snapshot()` call so a file marked orphaned in this
    call is never also deleted in the same call; it survives to be picked
    up by a later refresh's delete pass instead, preserving at least one
    full refresh cycle of visibility between marking and permanent
    removal. A `.orphaned` file no longer matches the glob below, so a
    later mark sweep leaves it alone rather than re-processing it every
    refresh.
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
        logger.info("Marked orphaned draft snapshot for future cleanup: %s -> %s", path.name, marked_path.name)


def _delete_orphaned_snapshots() -> None:
    """Permanently delete every `.orphaned`-marked snapshot file already on disk.

    Phase 2 of the two-phase orphan cleanup (see `_mark_orphaned_snapshots`)
    - added once Phase 1's marking step was confirmed correct against real
    production data, rather than assumed correct from launch. Called
    before `_mark_orphaned_snapshots` in `reconcile_snapshot()`, not after,
    so this only ever deletes a file that was already `.orphaned` coming
    into the current refresh - never one this same call is about to mark -
    which is what gives a human at least one full refresh cycle to notice
    and rename a wrongly-marked file back before it's gone for good.
    """
    if not CACHE_DIR.exists():
        return
    for path in CACHE_DIR.glob("draft_snapshots_*.json.orphaned"):
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
        # First time ever seeing this draft - baseline is "whatever the
        # roster looks like right now." Nothing before this point is
        # retroactively attributable, by definition.
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
        # Multiple own-picks completed since the last refresh - can't
        # isolate which drop paired with which pick.
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
