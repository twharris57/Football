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

    cap = state["roster_capacity"]
    print(
        f"\n--- Roster capacity ---\n"
        f"Active roster: {cap['active_filled']}/{cap['active_total']} filled "
        f"({cap['active_open']} open)\n"
        f"Taxi squad:    {cap['taxi_filled']}/{cap['taxi_total']} filled "
        f"({cap['taxi_open']} open)"
    )

    print("\n--- Your roster needs ---")
    print(state["roster_needs"].to_string() if not state["roster_needs"].empty else "(empty roster)")
    needs = state["need_positions"]
    print(f"Flagged needs: {', '.join(sorted(needs))}" if needs else "No positions flagged as a need right now.")

    print(
        "\n--- Roster value analysis (lowest value first) ---\n"
        "Same FantasyCalc values as the big board, so the same scoring-mismatch caveat "
        "applies (QB/TE likely undervalued here). 'note' weighs age: low value + young is "
        "still a rebuild asset, low value + aging is a real drop candidate."
    )
    print(state["roster_value"].to_string(index=False) if not state["roster_value"].empty else "(empty roster)")

    print("\n--- Bye week conflicts (2+ players at a position sharing a bye) ---")
    conflicts = state["roster_bye_conflicts"]
    print(conflicts.to_string(index=False) if not conflicts.empty else "(none)")

    print("\n--- Handcuff status (your rostered RB starters) ---")
    handcuffs = state["roster_handcuffs"]
    print(handcuffs.to_string(index=False) if not handcuffs.empty else "(none of your RBs are NFL starters)")

    if not state["recent_picks"].empty:
        print("\n--- Recently drafted ---")
        print(state["recent_picks"].to_string(index=False))

    print(
        "\n--- Available rookies (big board) ---\n"
        "tier = FantasyCalc's global dynasty tier across ALL players, not rookie-specific "
        "(gaps are veterans/other rookies not shown here). rank = order within this rookie-only "
        "list. fits_need = position is currently flagged as a roster need. handcuff_to = this "
        "rookie backs up one of your own RB starters, if any."
    )
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
