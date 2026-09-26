"""The trade-block list: which players other managers have declared
available to trade, tracked live in `trade_block_store.py`'s SQLite store
and managed through the Trade Block subtab (`dynasty/tabs/trade_tab.py`).

Sleeper's public API has no trade-block concept of its own (confirmed
live, 2026-09-03 - this league's real `/league/{id}/rosters` response has
no `trade_block`-shaped key anywhere, and Sleeper's own API docs list no
such endpoint). Who's on the block is purely what gets mentioned in league
chat, entered by hand through the app's own UI.

This module holds `TradeBlockEntry` (the shared row shape both the store
and the tab use) plus `prune_stale_entries()` - the pure decision logic
for "does this entry still make sense" (a player traded away or dropped
from the roster they were blocked under no longer belongs on the list).
Kept pure and `st.*`-free so it's directly unit-testable, per
`confidence_pool_principles.md`'s "business logic that decides what gets
persisted belongs in the tested library, not the panel" rule - the tab
calls this, then persists whatever it returns via `trade_block_store.py`.
"""

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
    """Split `entries` into (still-valid, stale) by checking each entry's
    player against the roster they were blocked under.

    An entry is stale the moment its player is no longer on
    `rosters_by_id[entry.roster_id]`'s live player list - regardless of
    where they ended up, since the point of an entry is "this specific
    roster is shopping this player," and that's no longer true either way.
    Classified as "traded" if the player is still rostered by someone else
    in the league (`rostered_player_ids`, the same helper
    `state.py`/`player_pools.py` already use for "is this player rostered
    by anyone" checks elsewhere), or "dropped" if they're not rostered by
    anyone. A `roster_id` with no matching entry in `rosters_by_id` (the
    roster itself no longer exists, e.g. a league-membership change) is
    treated the same as "player not on that roster" - stale, classified by
    the same traded/dropped rule.

    Pure - no I/O, no `st.*` calls. Callers persist the removal themselves.
    """
    all_rostered = rostered_player_ids(list(rosters_by_id.values()))

    kept = []
    removed = []
    for entry in entries:
        roster = rosters_by_id.get(entry.roster_id) or {}
        current_players = roster.get("players") or []
        if entry.sleeper_id in current_players:
            kept.append(entry)
            continue
        reason = "traded" if entry.sleeper_id in all_rostered else "dropped"
        removed.append(PrunedEntry(entry=entry, reason=reason))

    return tuple(kept), tuple(removed)
