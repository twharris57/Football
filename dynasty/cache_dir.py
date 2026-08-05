"""Shared on-disk cache location for the dynasty tools.

Anchored to the repo root explicitly (not `Path(__file__).parent`) so the
actual on-disk/in-container path stays `<repo root>/.cache` regardless of
which module resolves it or how deep in the tree that module lives -
matters in particular for the Docker deployment's named volume mount.
"""

from __future__ import annotations

from pathlib import Path

CACHE_DIR = Path(__file__).parent.parent / ".cache"
