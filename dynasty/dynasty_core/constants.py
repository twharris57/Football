"""Constants shared across more than one dynasty_core submodule.

Single-module constants live with the functions that use them instead.
"""

from __future__ import annotations

from cache_dir import CACHE_DIR

DEFAULT_LEAGUE_ID = "1324888291937386496"
DEFAULT_USERNAME = "twharris57"
FANTASY_POSITIONS = ("QB", "RB", "WR", "TE")
FLEX_ELIGIBLE_POSITIONS = frozenset({"RB", "WR", "TE"})
SUPERFLEX_ELIGIBLE_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})
YOUNG_CORE_NEED_THRESHOLD = 2
NFL_WEEKS = range(1, 19)

# CACHE_DIR is re-exported here (not just imported for local use) so every
# other dynasty_core submodule can keep doing `from .constants import CACHE_DIR`.
__all__ = [
    "CACHE_DIR",
    "DEFAULT_LEAGUE_ID",
    "DEFAULT_USERNAME",
    "FANTASY_POSITIONS",
    "FLEX_ELIGIBLE_POSITIONS",
    "NFL_WEEKS",
    "SUPERFLEX_ELIGIBLE_POSITIONS",
    "YOUNG_CORE_NEED_THRESHOLD",
]
