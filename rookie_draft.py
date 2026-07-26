"""CLI for the rookie draft big board (see dynasty_core.py for the logic).

Run during the draft with the interactive refresh loop (default) so the
board updates as picks come off the board:

    python rookie_draft.py
    python rookie_draft.py --once            # one snapshot, no prompt
    python rookie_draft.py --league-id 123 --username someone
"""

from __future__ import annotations

import argparse
import logging
from typing import Any

import dynasty_core

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def print_report(state: dict[str, Any]) -> None:
    """Print a full draft-state snapshot: on the clock, your picks, roster needs, big board."""
    league = state["league"]
    print(f"\n=== {league['name']} - {league['season']} Rookie Draft ({league['status']}) ===\n")

    total_picks = len(state["ownership"])
    current_pick_no = state["current_pick_no"]
    if current_pick_no > total_picks:
        print("Draft complete.\n")
    else:
        on_the_clock = next(p for p in state["ownership"] if p.overall_pick == current_pick_no)
        clock_team = state["team_names"][on_the_clock.owner_roster_id]
        print(f"On the clock: pick {current_pick_no}/{total_picks} - {clock_team}\n")

    print("--- Your picks ---")
    print(state["your_picks"].to_string(index=False) if not state["your_picks"].empty else "(none)")

    print("\n--- Your roster needs ---")
    print(state["roster_needs"].to_string() if not state["roster_needs"].empty else "(empty roster)")

    if not state["recent_picks"].empty:
        print("\n--- Recently drafted ---")
        print(state["recent_picks"].to_string(index=False))

    print("\n--- Available rookies (big board) ---")
    board = state["big_board"]
    if board.empty:
        print("(no rookies available)")
    else:
        for tier in sorted(board["tier"].unique()):
            print(f"\nTier {tier}:")
            print(board[board["tier"] == tier].drop(columns="tier").to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--league-id", default=dynasty_core.DEFAULT_LEAGUE_ID)
    parser.add_argument("--username", default=dynasty_core.DEFAULT_USERNAME)
    parser.add_argument("--once", action="store_true", help="print one snapshot and exit")
    args = parser.parse_args()

    force_refresh_players = False
    while True:
        state = dynasty_core.gather_state(args.league_id, args.username, force_refresh_players)
        force_refresh_players = False
        print_report(state)

        if args.once:
            break

        choice = input("\n[Enter] refresh picks  |  f = full refresh (players+values)  |  q = quit: ")
        choice = choice.strip().lower()
        if choice == "q":
            break
        if choice == "f":
            force_refresh_players = True


if __name__ == "__main__":
    main()
