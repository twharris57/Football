"""Trade-block list: which players other managers have declared available to
trade, tracked as a small hand-maintained file checked into `main` - not
app state, and not `scout-data` (the cloud routine's own separate memory).

Sleeper's public API has no trade-block concept at all (confirmed live,
2026-09-03 - this league's real `/league/{id}/rosters` response has no
`trade_block`-shaped key anywhere, and Sleeper's own API docs list no such
endpoint). Who's on the block is purely what gets mentioned in league
chat, so there's no automated source - entries are added by hand, typically
via a local Claude Code session with live Sleeper access to resolve a
player's name to their `sleeper_id` at the time they're added.

Stores only opaque identifiers (`sleeper_id`, `roster_id`) plus when each
entry was added - never a cached player name or NFL team, which would
drift the moment either changes (see valuation_principles.md's "opaque
keys" rule). Callers resolve display details live via
`sleeper_api.get_players()` and `team_name_by_roster_id()`, the same as
every other consumer of Sleeper's player/roster data.

This module only reads the file - edits happen directly to trade_block.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

TRADE_BLOCK_PATH = Path(__file__).parent.parent / "trade_block.json"

_REQUIRED_TOP_KEYS = frozenset({"updated_at", "entries"})
_REQUIRED_ENTRY_KEYS = frozenset({"sleeper_id", "roster_id", "added_date"})


@dataclass(frozen=True)
class TradeBlockEntry:
    sleeper_id: str
    roster_id: int
    added_date: str  # "YYYY-MM-DD" - when this entry was added to the block


def _require_iso_date(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid YYYY-MM-DD date: {value!r}") from exc
    if parsed.strftime("%Y-%m-%d") != value:
        raise ValueError(f"{label} must be zero-padded YYYY-MM-DD, got {value!r}")
    return value


def _parse_entry(payload: object, index: int) -> TradeBlockEntry:
    if not isinstance(payload, dict) or set(payload) != _REQUIRED_ENTRY_KEYS:
        raise ValueError(f"entries[{index}] must have exactly the keys {sorted(_REQUIRED_ENTRY_KEYS)}, got {payload!r}")

    sleeper_id = payload["sleeper_id"]
    if not isinstance(sleeper_id, str) or not sleeper_id:
        raise ValueError(f"entries[{index}].sleeper_id must be a non-empty string")

    roster_id = payload["roster_id"]
    if not isinstance(roster_id, int) or isinstance(roster_id, bool):
        raise ValueError(f"entries[{index}].roster_id must be an int")

    added_date = _require_iso_date(payload["added_date"], f"entries[{index}].added_date")

    return TradeBlockEntry(sleeper_id=sleeper_id, roster_id=roster_id, added_date=added_date)


def load_trade_block(path: Path = TRADE_BLOCK_PATH) -> tuple[TradeBlockEntry, ...]:
    """Load and validate trade_block.json's entries.

    Returns an empty tuple if the file doesn't exist yet - no trade-block
    activity tracked is a normal state, not an error, since this file is
    optional, hand-maintained data. Raises ValueError on a structurally
    malformed file (unknown/missing keys, wrong types, a duplicate
    sleeper_id) - a schema-drift or hand-edit-mistake signal, not routine
    bad data to skip past silently, same posture as
    scout_api/finding_schema.py's parser.
    """
    if not path.exists():
        return ()

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != _REQUIRED_TOP_KEYS:
        raise ValueError(f"trade_block.json must have exactly the keys {sorted(_REQUIRED_TOP_KEYS)}, got {payload!r}")

    _require_iso_date(payload["updated_at"], "updated_at")

    entries_payload = payload["entries"]
    if not isinstance(entries_payload, list):
        raise ValueError(f"entries must be a JSON array, got {type(entries_payload).__name__}")

    entries = tuple(_parse_entry(item, index) for index, item in enumerate(entries_payload))

    seen_ids = set()
    for entry in entries:
        if entry.sleeper_id in seen_ids:
            raise ValueError(f"duplicate sleeper_id {entry.sleeper_id!r} in trade_block.json")
        seen_ids.add(entry.sleeper_id)

    return entries
