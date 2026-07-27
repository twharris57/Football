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
import sys
from typing import Any

import pandas as pd
import requests

import dynasty_core

# Status flags (see dynasty_core.player_status_flags) and draft-plan status
# icons print emoji - Windows consoles default to cp1252, which can't
# encode them and crashes the whole report with a UnicodeEncodeError.
# Force UTF-8 stdout regardless of the platform's default codepage.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def render_df(df: pd.DataFrame, empty_message: str, *, index: bool = False) -> str:
    """Return df as a plain-text table, or empty_message if it's empty.

    The repeated print shape across every section below - most tables use
    a meaningless default index (index=False); roster_needs is grouped by
    position, where the index is the point, so it opts into index=True.
    """
    return df.to_string(index=index) if not df.empty else empty_message


def print_report(state: dict[str, Any]) -> None:
    """Print a full draft-state snapshot: on the clock, your picks, roster needs, big board."""
    league = state["league"]
    print(f"\n=== {league['name']} - {league['season']} Rookie Draft ({league['status']}) ===\n")

    for warning in state["data_warnings"]:
        print(f"WARNING: {warning}")

    total_picks = len(state["ownership"])
    current_pick_no = state["current_pick_no"]
    if current_pick_no > total_picks:
        print("Draft complete.\n")
    else:
        on_the_clock = next(p for p in state["ownership"] if p.overall_pick == current_pick_no)
        clock_team = state["team_names"][on_the_clock.owner_roster_id]
        until_turn = state["picks_until_turn"]
        if until_turn is None:
            turn_note = " (no picks left this draft)"
        elif until_turn == 0:
            turn_note = " (your turn!)"
        else:
            turn_note = f" ({until_turn} pick{'s' if until_turn != 1 else ''} until your turn)"
        print(f"On the clock: pick {current_pick_no}/{total_picks} - {clock_team}{turn_note}\n")

    print(
        "--- Draft plan (every pick you own this draft) ---\n"
        "Picks are ranked by season-average MARGINAL starting-lineup value, not raw trade value:\n"
        "for each candidate, simulate adding them (+ the resulting drop) and measure how much your\n"
        "roster's season-average starting value goes up, bye weeks included in that average - not\n"
        "raw player value with a needs override. A modest player at a weak position can beat a highly\n"
        "valued one who wouldn't crack your lineup. status=completed rows show the REAL pick Sleeper\n"
        "recorded, scored the same way retroactively; status=upcoming rows are simulated, assuming no\n"
        "other team's picks happen in between - 'if these were your only remaining picks, back to back,\n"
        "on the board right now.' drop_name is a live suggestion even for completed rounds - Sleeper has\n"
        "no record of whether it was actually dropped. Refresh after any pick lands for an updated plan."
    )
    plan = state["multi_round_plan"]
    print(render_df(plan["rounds"], "(no picks owned this draft)"))
    if not plan["rounds"].empty:
        if plan["rounds"]["drop_is_starter"].any():
            print("NOTE: at least one recommended drop is a current starter - see drop_is_starter above.")

        alternates_by_pick = plan["alternates_by_pick"]
        for _, row in plan["rounds"].iterrows():
            alternates = alternates_by_pick.get(row["overall_pick"])
            if alternates is not None and not alternates.empty:
                print(f"  Backup options for pick {row['overall_pick']} (round {row['round']}):")
                print(alternates.to_string(index=False))
    if not plan["weekly_gap_alerts"].empty:
        print("ALERT: this plan would introduce/worsen a weekly gap:")
        print(plan["weekly_gap_alerts"].to_string(index=False))
    else:
        print("This plan does not introduce any new weekly gaps.")

    print("\n--- Lineup (optimal current starters, value-only snapshot) ---")
    print(state["lineup_starters"].to_string(index=False))
    print("Bench (top 5 by value):")
    print(render_df(state["lineup_bench"].head(5), "(empty)"))
    print("Taxi squad:")
    print(render_df(state["lineup_taxi"], "(empty)"))
    print("IR / Reserve:")
    print(render_df(state["lineup_ir"], "(empty)"))

    print("\n--- Your picks ---")
    print(render_df(state["your_picks"], "(none)"))

    cap = state["roster_capacity"]
    print(
        f"\n--- Roster capacity ---\n"
        f"Active roster: {cap['active_filled']}/{cap['active_total']} filled "
        f"({cap['active_open']} open)\n"
        f"Taxi squad:    {cap['taxi_filled']}/{cap['taxi_total']} filled "
        f"({cap['taxi_open']} open)\n"
        f"IR / Reserve:  {cap['reserve_filled']}/{cap['reserve_total']} filled "
        f"({cap['reserve_open']} open)"
    )

    print("\n--- Your roster needs ---")
    print(render_df(state["roster_needs"], "(empty roster)", index=True))
    needs = state["need_positions"]
    print(f"Flagged needs: {', '.join(sorted(needs))}" if needs else "No positions flagged as a need right now.")

    print(
        "\n--- Roster value analysis (lowest adj_value first) ---\n"
        "Same real-scoring-corrected value as the big board (raw 'value' kept alongside for "
        "comparison). status: \U0001f195 rookie (no NFL experience yet), \U0001f3e5 + injury "
        "code, \U0001f331 taxi, \U0001fa79 IR/reserve. 'note' weighs age against a position-aware "
        "aging cutoff: low value + young is still a rebuild asset, low value + aging is a real "
        "drop candidate."
    )
    print(render_df(state["roster_value"], "(empty roster)"))

    print(
        "\n--- Bye week impact (weeks with an active-roster player out; "
        "lineup_delta = starting-lineup value vs. a full-strength week) ---"
    )
    print(render_df(state["roster_bye_conflicts"], "(none)"))

    print(
        "\n--- Weekly gaps (dedicated QB/RB/WR/TE slots only, not FLEX/SUPER_FLEX) ---\n"
        "Available (non-bye) rostered players per position per week, vs. what's needed to "
        "fill this league's dedicated starting slots (QB:1 RB:2 WR:2 TE:1). Does not account "
        "for FLEX/SUPER_FLEX, which could pull from other positions."
    )
    weekly_gaps = state["roster_weekly_gaps"]
    print(weekly_gaps.to_string(index=False))
    gap_weeks = weekly_gaps[weekly_gaps["gap"] != ""]
    if not gap_weeks.empty:
        print("Weeks with a gap:")
    print(render_df(gap_weeks, "No weeks have a dedicated-slot gap."))

    print("\n--- Handcuff status (your rostered RB starters) ---")
    print(render_df(state["roster_handcuffs"], "(none of your RBs are NFL starters)"))

    if not state["recent_picks"].empty:
        print("\n--- Recently drafted ---")
        print(state["recent_picks"].to_string(index=False))

    print(
        "\n--- Rookie big board (whole class - drafted players stay listed) ---\n"
        "tier = FantasyCalc's global dynasty tier across ALL players, not rookie-specific "
        "(gaps are veterans/other rookies not shown here). rank = value order across the WHOLE "
        "class, drafted and undrafted together. fits_need = position is currently flagged as a "
        "roster need. handcuff_to = this rookie backs up one of your own RB starters, if any - "
        "expect this to be sparse pre-season since nfl_data_py's player-ID crosswalk hasn't "
        "caught up with most of this year's incoming class yet, not a bug. "
        "drafted_round/drafted_by = blank if still undrafted."
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

    force_full_refresh = False
    while True:
        try:
            state = dynasty_core.gather_state(args.league_id, args.username, force_full_refresh)
        except requests.RequestException as exc:
            # A hiccup here shouldn't kill the whole session - everyone hits
            # Sleeper/FantasyCalc at once on draft day, so a transient error
            # is expected, not exceptional. Let the user retry or bail.
            print(f"\nCouldn't reach Sleeper/FantasyCalc: {exc}")
            if args.once:
                raise
            choice = input("[Enter] retry  |  q = quit: ").strip().lower()
            if choice == "q":
                break
            continue
        except (ValueError, TypeError) as exc:
            # A bad --league-id or typo'd --username (e.g. resolve_user_roster_id's
            # "no user found") - not transient, so retrying with the same args
            # won't help. Streamlit already handles this the same way (st.error
            # + st.stop()); the CLI equivalent is a clean message and exit,
            # not an ugly traceback or an infinite retry loop.
            print(f"\n{exc}")
            raise SystemExit(1) from exc

        force_full_refresh = False
        print_report(state)

        if args.once:
            break

        choice = input("\n[Enter] refresh picks  |  f = full refresh (players+values)  |  q = quit: ")
        choice = choice.strip().lower()
        if choice == "q":
            break
        if choice == "f":
            force_full_refresh = True


if __name__ == "__main__":
    main()
