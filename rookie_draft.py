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

    print(
        "--- Recommended strategy ---\n"
        "Heuristic synthesis of the signals below (need fit, handcuff, age-aware drop note), "
        "not a new model. Values behind this use the QB/TE scoring correction "
        f"(QB x{dynasty_core.POSITION_VALUE_MULTIPLIER['QB']}, TE x{dynasty_core.POSITION_VALUE_MULTIPLIER['TE']}, "
        "see dynasty_core.py) but not the smaller long-TD/first-down bonus gaps."
    )
    strategy = state["strategy"]
    top_pick = strategy["top_pick"]
    if top_pick:
        print(
            f"Top pick: {top_pick['name']} ({top_pick['pos']}, rank {top_pick['rank']}, tier {top_pick['tier']}) "
            f"- {top_pick['reason']}"
        )
        if not strategy["also_consider"].empty:
            print("Also consider:")
            print(strategy["also_consider"][["rank", "name", "pos", "adj_value", "tier"]].to_string(index=False))
    else:
        print("Top pick: (no rookies available)")
    if not strategy["drop_candidates"].empty:
        print("Consider dropping (to make roster room):")
        print(strategy["drop_candidates"][["name", "pos", "age", "adj_value", "note"]].to_string(index=False))

    print(
        "\n--- Draft plan (your remaining picks this draft) ---\n"
        "Assumes no other team's picks happen in between - 'if these were your only picks, "
        "back to back, on the board right now.' Refresh after any pick lands (yours or "
        "anyone else's) to get an updated plan against the real board."
    )
    plan = state["multi_round_plan"]
    if plan["rounds"].empty:
        print("(no upcoming picks)")
    else:
        print(plan["rounds"].to_string(index=False))
        if plan["rounds"]["drop_is_starter"].any():
            print("NOTE: at least one recommended drop is a current starter - see drop_is_starter above.")
    if not plan["weekly_gap_alerts"].empty:
        print("ALERT: this plan would introduce/worsen a weekly gap:")
        print(plan["weekly_gap_alerts"].to_string(index=False))
    else:
        print("This plan does not introduce any new weekly gaps.")

    print("\n--- Lineup (optimal current starters, value-only snapshot) ---")
    print(state["lineup_starters"].to_string(index=False))
    print("Bench (top 5 by value):")
    print(state["lineup_bench"].head(5).to_string(index=False) if not state["lineup_bench"].empty else "(empty)")

    print("\n--- Your picks ---")
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
        "\n--- Roster value analysis (lowest adj_value first) ---\n"
        "Same QB/TE-corrected value as the big board (raw 'value' kept alongside for "
        "comparison). 'note' weighs age: low value + young is still a rebuild asset, "
        "low value + aging is a real drop candidate."
    )
    print(state["roster_value"].to_string(index=False) if not state["roster_value"].empty else "(empty roster)")

    print("\n--- Bye week conflicts (2+ players at a position sharing a bye) ---")
    conflicts = state["roster_bye_conflicts"]
    print(conflicts.to_string(index=False) if not conflicts.empty else "(none)")

    print(
        "\n--- Weekly gaps (dedicated QB/RB/WR/TE slots only, not FLEX/SUPER_FLEX) ---\n"
        "Available (non-bye) rostered players per position per week, vs. what's needed to "
        "fill this league's dedicated starting slots (QB:1 RB:2 WR:2 TE:1). Does not account "
        "for FLEX/SUPER_FLEX, which could pull from other positions."
    )
    weekly_gaps = state["roster_weekly_gaps"]
    print(weekly_gaps.to_string(index=False))
    gap_weeks = weekly_gaps[weekly_gaps["gap"] != ""]
    print(
        "Weeks with a gap:\n" + gap_weeks.to_string(index=False)
        if not gap_weeks.empty
        else "No weeks have a dedicated-slot gap."
    )

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
