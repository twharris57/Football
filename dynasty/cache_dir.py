"""Dynasty cache directory: `<repo root>/.cache`, matching the Docker volume mount."""

from __future__ import annotations

from pathlib import Path

CACHE_DIR = Path(__file__).parent.parent / ".cache"
