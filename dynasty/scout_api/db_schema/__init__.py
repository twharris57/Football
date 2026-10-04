"""Migration runner for the scout-data mirror. Nested in `scout_api` so it can't clash with `confidence_pool/db_schema`."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Apply unrecorded `migrations/*.sql` files in numeric order, one transaction each."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(path.name.split("_", 1)[0])
        if version in applied:
            continue
        with conn:
            conn.executescript(path.read_text())
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, datetime.now(timezone.utc).isoformat()),
            )
