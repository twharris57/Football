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
mid-draft. No retention/cleanup: once a season's draft is over, its file is
simply never read again (next season gets a new draft_id from Sleeper).
"""

from __future__ import annotations

from typing import Any

from .constants import CACHE_DIR
from .picks import DraftPickSlot
from .snapshot_io import load_or_seed, write_if_changed

AMBIGUOUS = "AMBIGUOUS"


def _snapshot_path(draft_id: str) -> Any:
    return CACHE_DIR / f"draft_snapshots_{draft_id}.json"


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
    path = _snapshot_path(draft_id)
    existing = load_or_seed(path, {"confirmed_through_pick": 0, "confirmed_roster": None, "confirmed_drops": {}})
    updated = _reconcile(existing, own_picks, current_pick_no, current_roster_ids, real_picks_by_overall)
    write_if_changed(path, existing, updated)
    return updated
