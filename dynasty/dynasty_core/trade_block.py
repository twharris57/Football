"""Trade-block row type and pruning logic (storage lives in `trade_block_store.py`)."""

from __future__ import annotations

from dataclasses import dataclass

from .player_pools import rostered_player_ids


@dataclass(frozen=True)
class TradeBlockEntry:
    sleeper_id: str
    roster_id: int
    added_date: str  # "YYYY-MM-DD" - when this entry was added to the block


@dataclass(frozen=True)
class PrunedEntry:
    entry: TradeBlockEntry
    reason: str  # "traded" | "dropped"


def prune_stale_entries(
    entries: tuple[TradeBlockEntry, ...], rosters_by_id: dict[int, dict]
) -> tuple[tuple[TradeBlockEntry, ...], tuple[PrunedEntry, ...]]:
    """Split entries into `(kept, pruned)`: pruned once the player leaves the roster they were listed under.

    Reason is "traded" if someone else rosters them, else "dropped". A missing roster
    prunes too. A roster that comes back empty is assumed to be a bad fetch, so its
    entries are kept (pruning can't be undone). Pure.
    """
    all_rostered = rostered_player_ids(list(rosters_by_id.values()))
    suspect_roster_ids = {
        roster_id for roster_id, roster in rosters_by_id.items() if not (roster.get("players") or [])
    }

    kept = []
    removed = []
    for entry in entries:
        if entry.roster_id in suspect_roster_ids:
            kept.append(entry)
            continue
        roster = rosters_by_id.get(entry.roster_id) or {}
        current_players = roster.get("players") or []
        if entry.sleeper_id in current_players:
            kept.append(entry)
            continue
        reason = "traded" if entry.sleeper_id in all_rostered else "dropped"
        removed.append(PrunedEntry(entry=entry, reason=reason))

    return tuple(kept), tuple(removed)
