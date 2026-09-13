"""Shared on-disk location for the scout-data SQLite mirror.

Anchored to the repo root explicitly (matching dynasty/cache_dir.py's and
confidence_pool/data_dir.py's pattern) so the on-disk/in-container path
stays stable regardless of which module resolves it - matters for the
Docker deployment's named volume mount. A separate directory from
dynasty/cache_dir.py's `.cache` on purpose: that one is an ephemeral,
12h-TTL API cache, while this mirror is meant to be durable (the whole
point of syncing it locally), so it needs its own backup-covered volume,
not to share the cache's lifecycle.
"""

from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "scout_data"
DB_PATH = DATA_DIR / "scout_data.db"
