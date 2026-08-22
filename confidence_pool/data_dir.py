"""Shared on-disk location for the confidence pool's SQLite store.

Anchored to the repo root explicitly (same reasoning as dynasty/cache_dir.py)
so the on-disk/in-container path stays stable regardless of which module
resolves it -- not a shared import with dynasty/cache_dir.py, though: the
two subsystems share no code (see CLAUDE.md's "Architecture").
"""

from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "confidence_pool_data"
DB_PATH = DATA_DIR / "picks.db"
