"""Streamlit dashboard for the rookie draft big board (see dynasty_core.py).

    streamlit run streamlit_app.py

Meant to be usable from a phone during the live draft: sidebar inputs for
league ID / username, a Refresh button (re-pulls league/rosters/draft/picks —
cheap, always live) and a Force full refresh button (also busts the on-disk
players.json cache) — the web equivalent of the CLI's Enter-vs-`f` prompt.
"""

from __future__ import annotations

import requests
import streamlit as st

import dynasty_core

st.set_page_config(page_title="Dynasty Rookie Draft", layout="centered")

st.sidebar.header("League")
league_id = st.sidebar.text_input("League ID", value=dynasty_core.DEFAULT_LEAGUE_ID)
username = st.sidebar.text_input("Username", value=dynasty_core.DEFAULT_USERNAME)

if "refresh_token" not in st.session_state:
    st.session_state.refresh_token = 0

refresh = st.sidebar.button("Refresh")
force_full = st.sidebar.button("Force full refresh (players + values)")
if refresh or force_full:
    st.session_state.refresh_token += 1


@st.cache_data(show_spinner="Loading draft state...")
def load_state(league_id: str, username: str, force_refresh_players: bool, _token: int) -> dict:
    return dynasty_core.gather_state(league_id, username, force_refresh_players)


st.title("Dynasty Rookie Draft")

try:
    state = load_state(league_id, username, force_full, st.session_state.refresh_token)
except requests.RequestException as exc:
    st.error(f"Couldn't reach Sleeper/FantasyCalc: {exc}. Hit Refresh to try again.")
    st.stop()
except ValueError as exc:
    st.error(str(exc))
    st.stop()

league = state["league"]
st.caption(f"{league['name']} - {league['season']} Rookie Draft ({league['status']})")

total_picks = len(state["ownership"])
current_pick_no = state["current_pick_no"]
if current_pick_no > total_picks:
    st.success("Draft complete.")
else:
    on_the_clock = next(p for p in state["ownership"] if p.overall_pick == current_pick_no)
    clock_team = state["team_names"][on_the_clock.owner_roster_id]
    st.info(f"On the clock: pick {current_pick_no}/{total_picks} - {clock_team}")

plan_tab, lineup_tab, draft_tab, roster_tab = st.tabs(["Draft Plan", "Lineup", "Draft Board", "Your Roster"])

with plan_tab:
    st.caption(
        "Every pick you own this draft. Values apply this league's QB/TE scoring correction "
        f"(QB ×{dynasty_core.POSITION_VALUE_MULTIPLIER['QB']}, TE ×{dynasty_core.POSITION_VALUE_MULTIPLIER['TE']}) "
        "but not the smaller long-TD/first-down bonus gaps. **status=completed** rows show the "
        "REAL pick Sleeper recorded; **status=upcoming** rows are simulated (best value, "
        "preferring a flagged need), assuming no other team's picks happen in between — 'if "
        "these were your only remaining picks, back to back, on the board right now.' "
        "**drop_name** is a live suggestion even for completed rounds — Sleeper has no record "
        "of whether it was actually dropped. Refresh after any pick lands for an updated plan."
    )
    plan = state["multi_round_plan"]
    rounds = plan["rounds"]
    if rounds.empty:
        st.write("(no picks owned this draft)")
    else:
        st.dataframe(rounds, hide_index=True, width="stretch")
        if rounds["drop_is_starter"].any():
            st.warning("At least one recommended drop is a current starter — see drop_is_starter above.")

    st.subheader("Weekly gap impact")
    alerts = plan["weekly_gap_alerts"]
    if alerts.empty:
        st.success("This plan does not introduce any new weekly gaps.")
    else:
        st.warning("This plan would introduce or worsen a gap in these weeks:")
        st.dataframe(alerts, hide_index=True, width="stretch")

with lineup_tab:
    st.caption(
        "Optimal current lineup by value alone — a snapshot, not week-specific yet (doesn't "
        "account for byes or injuries when deciding who starts). A by-week/injury-aware version "
        "is a planned refinement."
    )
    st.subheader("Starters")
    st.dataframe(state["lineup_starters"], hide_index=True, width="stretch")
    st.subheader("Bench")
    bench = state["lineup_bench"]
    if bench.empty:
        st.write("(empty)")
    else:
        st.dataframe(bench, hide_index=True, width="stretch")

with draft_tab:
    st.subheader("Your picks")
    if state["your_picks"].empty:
        st.write("(none)")
    else:
        st.dataframe(state["your_picks"], hide_index=True, width="stretch")

    if not state["recent_picks"].empty:
        st.subheader("Recently drafted")
        st.dataframe(state["recent_picks"], hide_index=True, width="stretch")

    st.subheader("Rookie big board")
    st.caption(
        "The whole rookie class — drafted players stay listed instead of disappearing, "
        "annotated via **drafted_round**/**drafted_by** (blank if still undrafted). **rank** is "
        "value order across the whole class, drafted and undrafted together. **value** is "
        "FantasyCalc's raw number; **adj_value** applies this league's QB/TE scoring correction "
        "(see the Draft Plan tab) and is what determines sort order and **rank**. **tier** is "
        "FantasyCalc's own global tier across *all* players, not rookie-specific and not "
        "adjusted — gaps in the sequence are veterans/other rookies not shown here. "
        "**fits_need** flags a currently-thin position on your roster. "
        "**handcuff_to** means this rookie backs up one of your own RB starters."
    )
    board = state["big_board"]
    if board.empty:
        st.write("(no rookies available)")
    else:
        for tier in sorted(board["tier"].unique()):
            st.markdown(f"**Tier {tier}**")
            st.dataframe(
                board[board["tier"] == tier].drop(columns="tier"),
                hide_index=True,
                width="stretch",
            )

with roster_tab:
    st.subheader("Roster capacity")
    cap = state["roster_capacity"]
    cap_col1, cap_col2 = st.columns(2)
    cap_col1.metric("Active roster", f"{cap['active_filled']}/{cap['active_total']}", f"{cap['active_open']} open")
    cap_col2.metric("Taxi squad", f"{cap['taxi_filled']}/{cap['taxi_total']}", f"{cap['taxi_open']} open")
    if cap["active_open"] <= 0 and cap["taxi_open"] <= 0:
        st.warning("No open roster or taxi slots — drafting a rookie means dropping someone first.")

    st.subheader("Roster needs")
    if state["roster_needs"].empty:
        st.write("(empty roster)")
    else:
        st.dataframe(state["roster_needs"], width="stretch")
    needs = state["need_positions"]
    if needs:
        st.info(f"Flagged needs: {', '.join(sorted(needs))} — the big board marks rookies at these positions.")
    else:
        st.info("No positions are flagged as a need right now — best available value is the main signal.")

    st.subheader("Roster value analysis")
    st.caption(
        "Sorted lowest **adj_value** first (same QB/TE-corrected value as the big board). "
        "**note** weighs age: low value + young is still a rebuild asset worth holding; low "
        "value + aging is a real drop candidate."
    )
    roster_value = state["roster_value"]
    if roster_value.empty:
        st.write("(empty roster)")
    else:
        st.dataframe(roster_value, hide_index=True, width="stretch")

    st.subheader("Bye week conflicts")
    st.caption("Positions where 2+ of your players share the same bye week.")
    conflicts = state["roster_bye_conflicts"]
    if conflicts.empty:
        st.write("(none)")
    else:
        st.dataframe(conflicts, hide_index=True, width="stretch")

    st.subheader("Weekly gaps")
    st.caption(
        "Available (non-bye) rostered players per position per week, vs. what's needed to fill "
        "this league's dedicated starting slots (QB:1 RB:2 WR:2 TE:1). Does not account for "
        "FLEX/SUPER_FLEX, which could pull from other positions — a rough depth signal, not a "
        "full lineup-feasibility check."
    )
    weekly_gaps = state["roster_weekly_gaps"]
    gap_weeks = weekly_gaps[weekly_gaps["gap"] != ""]
    if gap_weeks.empty:
        st.write("No weeks have a dedicated-slot gap.")
    else:
        st.warning("Weeks with a gap:")
        st.dataframe(gap_weeks, hide_index=True, width="stretch")
    with st.expander("Show all 18 weeks"):
        st.dataframe(weekly_gaps, hide_index=True, width="stretch")

    st.subheader("Handcuff status")
    st.caption("Your rostered RBs who are NFL starters, and whether you also own their backup.")
    handcuffs = state["roster_handcuffs"]
    if handcuffs.empty:
        st.write("(none of your RBs are current NFL starters)")
    else:
        st.dataframe(handcuffs, hide_index=True, width="stretch")
