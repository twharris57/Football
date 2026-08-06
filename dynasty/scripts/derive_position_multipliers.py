"""Inspect the real-scoring multipliers used to correct FantasyCalc values.

Forces a fresh recompute (busts the disk cache) and pretty-prints the
per-player ratios and position averages that `player_scoring.get_multipliers`
would otherwise serve from cache — a standalone debug/sanity-check entry
point, not something the app itself needs to run.

    python scripts/derive_position_multipliers.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import dynasty_core as dc
import player_scoring
import sleeper_api as sleeper


def main() -> None:
    league = sleeper.get_league(dc.DEFAULT_LEAGUE_ID)
    result = player_scoring.get_multipliers(league["scoring_settings"], league["season"], force_refresh=True)

    print(f"Pooled seasons: {result['seasons']}")
    print()
    print("Position averages:")
    for pos, ratio in sorted(result["position_average"].items()):
        print(f"  {pos}: {ratio:.4f}")

    print()
    print(f"Per-player multipliers: {len(result['per_player'])} players with qualifying real NFL history")
    players = sleeper.get_players()
    named = [
        (players.get(pid, {}).get("full_name", pid), ratio)
        for pid, ratio in result["per_player"].items()
    ]
    for name, ratio in sorted(named, key=lambda p: p[1], reverse=True)[:15]:
        print(f"  {name}: {ratio:.4f}")
    print("  ...")
    for name, ratio in sorted(named, key=lambda p: p[1])[:15]:
        print(f"  {name}: {ratio:.4f}")

    print()
    rookie_bucket = result.get("rookie_bucket", {})
    print(f"Rookie play-style buckets: {len(rookie_bucket)} of this year's incoming class matched")
    for pid, ratio in sorted(rookie_bucket.items(), key=lambda p: p[1], reverse=True):
        name = players.get(pid, {}).get("full_name", pid)
        print(f"  {name}: {ratio:.4f}")


if __name__ == "__main__":
    main()
