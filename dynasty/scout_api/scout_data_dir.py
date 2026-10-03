"""Location of the scout-data SQLite mirror. Kept apart from `.cache` because it's durable, not a TTL cache."""

from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "scout_data"
DB_PATH = DATA_DIR / "scout_data.db"
