"""Schema migration runner for the confidence-pool SQLite store.

Applies every `*.sql` file under `migrations/` that `schema_migrations`
doesn't already record as applied, in ascending numeric-prefix order.
Named `db_schema`, not `schema`, to avoid ever colliding with the `schema`
PyPI package (a validation library) if that's added as a dependency
elsewhere -- see `docs/confidence-pool-data-model.md` for the schema's
full design.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Run any migration not yet recorded in `schema_migrations`, in
    ascending numeric order, each as its own transaction."""
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
