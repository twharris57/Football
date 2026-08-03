"""Constants shared across more than one dynasty_core submodule.

Single-module constants live with the functions that use them instead.
"""

from __future__ import annotations

from pathlib import Path

# One level up from this package dir to the repo root, same on-disk
# location `dynasty_core.py` used before the module split. Revisit if the
# package itself ever moves relative to the repo root.
CACHE_DIR = Path(__file__).parent.parent / ".cache"

DEFAULT_LEAGUE_ID = "1324888291937386496"
DEFAULT_USERNAME = "twharris57"
FANTASY_POSITIONS = ("QB", "RB", "WR", "TE")
FLEX_ELIGIBLE_POSITIONS = frozenset({"RB", "WR", "TE"})
SUPERFLEX_ELIGIBLE_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})
YOUNG_CORE_NEED_THRESHOLD = 2
NFL_WEEKS = range(1, 19)
