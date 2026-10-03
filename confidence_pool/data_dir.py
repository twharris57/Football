"""On-disk location of the confidence pool's SQLite store, anchored to the repo root."""

from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "confidence_pool_data"
DB_PATH = DATA_DIR / "picks.db"
