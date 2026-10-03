"""SQLite persistence for the trade-block list: which players other
managers have declared available to trade, managed live through the Trade
Block subtab (dynasty/tabs/trade_tab.py) rather than a hand-edited file.

Not named `store.py`/`data_dir.py` - those names are already claimed by
`confidence_pool/store.py`/`confidence_pool/data_dir.py`, and both
subsystems' directories land on the same `sys.path` together (see
`conftest.py`), so a same-named module here would silently shadow or be
shadowed by confidence_pool's - the same collision `panels/`/`tabs/`
already avoid by name, one level lower.

One table, no versioned-migrations directory - `confidence_pool/db_schema/`
earns that machinery from real, ongoing schema evolution (4 migrations and
counting); this starts from a single small table with no evolution history
yet. Add a proper migration runner if/when this actually needs one.

Sleeper's public API has no trade-block concept of its own (confirmed
live, 2026-09-03) - who's on the block is purely user-declared, entered
here by hand through the UI. Stores only opaque identifiers (`sleeper_id`,
`roster_id`) plus when each entry was added - never a cached player name
or NFL team, which would drift the moment either changes (see
valuation_principles.md's "opaque keys" rule). Callers resolve display
details live via `sleeper_api.get_players()`/`state["rosters_by_id"]`, the
same as every other consumer of Sleeper's player/roster data.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from dynasty_core.trade_block import TradeBlockEntry

DATA_DIR = Path(__file__).parent.parent / "dynasty_data"
DB_PATH = DATA_DIR / "trade_block.db"


def connect(db_path: str) -> sqlite3.Connection:
    """Open (creating the schema if needed) the trade-block SQLite store.

    Same `check_same_thread=False`/WAL/busy_timeout shape as
    `confidence_pool/store.py:connect` - callers are expected to open this
    once via `st.cache_resource` and reuse the same connection across every
    session's own ScriptRunner thread.
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_block (
            sleeper_id TEXT PRIMARY KEY,
            roster_id INTEGER NOT NULL,
            added_date TEXT NOT NULL
        )
        """
    )
    return conn


def get_trade_block(conn: sqlite3.Connection) -> tuple[TradeBlockEntry, ...]:
    """Return every current trade-block entry."""
    rows = conn.execute("SELECT sleeper_id, roster_id, added_date FROM trade_block").fetchall()
    return tuple(
        TradeBlockEntry(sleeper_id=row["sleeper_id"], roster_id=row["roster_id"], added_date=row["added_date"])
        for row in rows
    )


def add_trade_block_entry(conn: sqlite3.Connection, sleeper_id: str, roster_id: int, added_date: str) -> None:
    """Add a player to the trade block. Raises `sqlite3.IntegrityError` if
    `sleeper_id` is already on the block (the primary key) - callers should
    catch this and tell the user, not silently ignore a duplicate add."""
    with conn:
        conn.execute(
            "INSERT INTO trade_block (sleeper_id, roster_id, added_date) VALUES (?, ?, ?)",
            (sleeper_id, roster_id, added_date),
        )


def remove_trade_block_entry(conn: sqlite3.Connection, sleeper_id: str) -> None:
    """Remove a player from the trade block. A no-op if they're not on it."""
    with conn:
        conn.execute("DELETE FROM trade_block WHERE sleeper_id = ?", (sleeper_id,))
