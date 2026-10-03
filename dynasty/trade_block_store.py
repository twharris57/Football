"""SQLite store for the user-entered trade block (Sleeper has no trade-block API).

Not named `store.py` — it would collide with `confidence_pool/store.py` on a shared
`sys.path`. Stores only IDs; callers resolve names live.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from dynasty_core.trade_block import TradeBlockEntry

DATA_DIR = Path(__file__).parent.parent / "dynasty_data"
DB_PATH = DATA_DIR / "trade_block.db"


def connect(db_path: str) -> sqlite3.Connection:
    """Open the store, creating the table if needed. Shared across threads, like `confidence_pool.store.connect`."""
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
    """Add a player. Raises `sqlite3.IntegrityError` if already listed."""
    with conn:
        conn.execute(
            "INSERT INTO trade_block (sleeper_id, roster_id, added_date) VALUES (?, ?, ?)",
            (sleeper_id, roster_id, added_date),
        )


def remove_trade_block_entry(conn: sqlite3.Connection, sleeper_id: str) -> None:
    """Remove a player from the trade block. A no-op if they're not on it."""
    with conn:
        conn.execute("DELETE FROM trade_block WHERE sleeper_id = ?", (sleeper_id,))
