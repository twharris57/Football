"""Shared load/write shell for a persisted-across-refreshes JSON snapshot.

Factored out of draft_snapshots.py (RT-20) so a second, structurally different
snapshot type (pickup_snapshots.py, RT-9) doesn't reimplement the same
load-or-seed / write-only-if-changed shape independently - see
.claude/conventions/valuation_principles.md's pattern of two independent
copies of the same logic drifting apart over time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_or_seed(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    """Load `path`'s JSON content, or `default` if the file doesn't exist yet."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def write_if_changed(path: Path, existing: dict[str, Any], updated: dict[str, Any]) -> None:
    """Write `updated` to `path` only if it differs from `existing`.

    Avoids a disk write (and touching mtime) on a no-op refresh.
    """
    if updated != existing:
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(updated), encoding="utf-8")
