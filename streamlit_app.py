"""Streamlit dashboard for the rookie draft big board (see dynasty_core.py).

    streamlit run streamlit_app.py

Meant to be usable from a phone during the live draft: sidebar inputs for
league ID / username, a Refresh button (re-pulls league/rosters/draft/picks —
cheap, always live) and a Force full refresh button (also busts the on-disk
players.json cache) — the web equivalent of the CLI's Enter-vs-`f` prompt.
"""

from __future__ import annotations

import os

import pandas as pd
import requests
import streamlit as st

import dynasty_core

APP_VERSION = os.environ.get("GIT_SHA", "dev")[:7]


def show_df(df: pd.DataFrame, empty_message: str, *, hide_index: bool = True) -> bool:
    """Render df, or empty_message if it's empty - the repeated shape across every tab.

    Returns whether df had rows, so callers can compose extra logic (an
    extra warning, an expander) on the non-empty path.
    """
    if df.empty:
        st.write(empty_message)
        return False
    st.dataframe(df, hide_index=hide_index, width="stretch")
    return True

st.set_page_config(page_title="Dynasty Rookie Draft", layout="centered")

if "league_name" not in st.session_state:
    st.session_state.league_name = "League"

st.sidebar.header(st.session_state.league_name)
league_id = st.sidebar.text_input("League ID", value=dynasty_core.DEFAULT_LEAGUE_ID)
username = st.sidebar.text_input("Username", value=dynasty_core.DEFAULT_USERNAME)

if "refresh_token" not in st.session_state:
    st.session_state.refresh_token = 0
if "force_refresh_pending" not in st.session_state:
    st.session_state.force_refresh_pending = False

refresh = st.sidebar.button("Refresh")
force_full = st.sidebar.button("Force full refresh (players + values)")
if refresh or force_full:
    st.session_state.refresh_token += 1
    # A widget button's return value is only True on the exact run it was
    # clicked - any later rerun (e.g. opening an expander) sees False again.
    # load_state's cache key must not depend on that raw, one-run-only value
    # (it did before - see PROJECT_PLAN.md), or the very next rerun after a
    # force-refresh click gets a different key, misses cache, and silently
    # re-fetches both APIs for no reason. force_refresh_pending is durable
    # session_state instead, so it stays stable across reruns until the next
    # actual button click changes refresh_token again.
    st.session_state.force_refresh_pending = force_full


@st.cache_data(show_spinner="Loading draft state...")
def load_state(league_id: str, username: str, force_full_refresh: bool, _token: int) -> dict:
    return dynasty_core.gather_state(league_id, username, force_full_refresh)


st.title("Dynasty Rookie Draft")

try:
    state = load_state(
        league_id, username, st.session_state.force_refresh_pending, st.session_state.refresh_token
    )
except requests.RequestException as exc:
    st.error(f"Couldn't reach Sleeper/FantasyCalc: {exc}. Hit Refresh to try again.")
    st.stop()
except ValueError as exc:
    st.error(str(exc))
    st.stop()

league = state["league"]
st.session_state.league_name = league["name"]
st.caption(f"{league['name']} - {league['season']} Rookie Draft ({league['status']})")

for warning in state["data_warnings"]:
    st.warning(warning)

total_picks = len(state["ownership"])
current_pick_no = state["current_pick_no"]
if current_pick_no > total_picks:
    st.success("Draft complete.")
else:
    on_the_clock = next(p for p in state["ownership"] if p.overall_pick == current_pick_no)
    clock_team = state["team_names"][on_the_clock.owner_roster_id]
    until_turn = state["picks_until_turn"]
    if until_turn is None:
        turn_note = " (no picks left this draft)"
    elif until_turn == 0:
        turn_note = " — **your turn!**"
    else:
        turn_note = f" ({until_turn} pick{'s' if until_turn != 1 else ''} until your turn)"
    st.info(f"On the clock: pick {current_pick_no}/{total_picks} - {clock_team}{turn_note}")

plan_tab, lineup_tab, draft_tab, roster_tab = st.tabs(["Draft Plan", "Lineup", "Draft Board", "Your Roster"])

with plan_tab:
    with st.expander("How this works"):
        st.caption(
            "Picks are ranked by season-average **marginal** starting-lineup value, not raw trade "
            "value: for each candidate, this simulates adding them (+ the resulting drop) and "
            "measures how much your roster's season-average starting value goes up — bye weeks are "
            "folded into that average, not handled separately. A modest player at a weak position "
            "can beat a highly-valued one who wouldn't crack your lineup. ✅ marks a round Sleeper "
            "has already recorded, scored the same way retroactively; 🔜 rounds are simulated, "
            "assuming no other team's picks happen in between — 'if these were your only remaining "
            "picks, back to back, on the board right now.' The suggested drop is a live suggestion "
            "even for a completed round — Sleeper has no record of whether it was actually dropped. "
            "⚠️ flags a suggested drop that's a current starter. Refresh after any pick lands for an "
            "updated plan. Each pick is collapsed by default — expand one for the full reasoning and "
            "any backup options."
        )
    plan = state["multi_round_plan"]
    rounds = plan["rounds"]
    if rounds.empty:
        st.write("(no picks owned this draft)")
    else:
        alternates_by_pick = plan["alternates_by_pick"]
        for _, row in rounds.iterrows():
            status_icon = "✅" if row["status"] == "completed" else "🔜"
            drop_part = f" · DROP {row['drop_name']} ({row['drop_pos']})" if pd.notna(row["drop_name"]) else ""
            warn_icon = " ⚠️" if row["drop_is_starter"] else ""
            label = (
                f"{status_icon} Round {row['round']}, pick {row['overall_pick']}: "
                f"DRAFT {row['pick_name']} ({row['pick_pos']}){drop_part}{warn_icon} · "
                f"{row['marginal_value']:+.0f}"
            )
            with st.expander(label):
                st.write(row["reason"])
                if row["drop_is_starter"]:
                    st.warning(f"{row['drop_name']} is a current starter.")
                alternates = alternates_by_pick.get(row["overall_pick"])
                if alternates is not None and not alternates.empty:
                    st.caption("Backup options for this pick:")
                    st.dataframe(alternates, hide_index=True, width="stretch")

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
    show_df(state["lineup_bench"], "(empty)")
    st.subheader("Taxi squad")
    show_df(state["lineup_taxi"], "(empty)")
    st.subheader("IR / Reserve")
    show_df(state["lineup_ir"], "(empty)")

with draft_tab:
    st.subheader("Your picks")
    show_df(state["your_picks"], "(none)")

    if not state["recent_picks"].empty:
        st.subheader("Recently drafted")
        st.dataframe(state["recent_picks"], hide_index=True, width="stretch")

    st.subheader("Rookie big board")
    st.caption(
        "The whole rookie class — drafted players stay listed instead of disappearing, "
        "annotated via **drafted_round**/**drafted_by** (blank if still undrafted). **rank** is "
        "value order across the whole class, drafted and undrafted together. **value** is "
        "FantasyCalc's raw number; **adj_value** applies this league's real-scoring correction "
        "(see the Draft Plan tab) and is what determines sort order and **rank**. **tier** is "
        "FantasyCalc's own global tier across *all* players, not rookie-specific and not "
        "adjusted — gaps in the sequence are veterans/other rookies not shown here. "
        "**fits_need** flags a currently-thin position on your roster. "
        "**handcuff_to** means this rookie backs up one of your own RB starters — expect this "
        "to be sparse pre-season: `nfl_data_py`'s player-ID crosswalk hasn't caught up with most "
        "of this year's incoming class yet, not a bug, and should fill in later in the year."
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
    cap_col1, cap_col2, cap_col3 = st.columns(3)
    cap_col1.metric("Active roster", f"{cap['active_filled']}/{cap['active_total']}", f"{cap['active_open']} open")
    cap_col2.metric("Taxi squad", f"{cap['taxi_filled']}/{cap['taxi_total']}", f"{cap['taxi_open']} open")
    cap_col3.metric("IR / Reserve", f"{cap['reserve_filled']}/{cap['reserve_total']}", f"{cap['reserve_open']} open")
    if cap["active_open"] <= 0 and cap["taxi_open"] <= 0:
        st.warning("No open roster or taxi slots — drafting a rookie means dropping someone first.")

    st.subheader("Roster needs")
    show_df(state["roster_needs"], "(empty roster)", hide_index=False)
    needs = state["need_positions"]
    if needs:
        st.info(f"Flagged needs: {', '.join(sorted(needs))} — the big board marks rookies at these positions.")
    else:
        st.info("No positions are flagged as a need right now — best available value is the main signal.")

    st.subheader("Roster value analysis")
    st.caption(
        "Sorted lowest **adj_value** first (same real-scoring-corrected value as the big board). "
        "**note** weighs age against a position-aware aging cutoff (RBs decline earlier than "
        "QBs/TEs): low value + young is still a rebuild asset worth holding; low value + aging "
        "is a real drop candidate."
    )
    show_df(state["roster_value"], "(empty roster)")

    st.subheader("Bye week impact")
    st.caption(
        "One collapsible section per week with an active-roster player on bye — collapsed shows "
        "only starters actually bumped out and who fills in, plus the lineup-value delta vs. a "
        "full-strength week; a bye'd bench player who wasn't starting anyway doesn't clutter the "
        "collapsed view (it's still there, expanded, since it doesn't move the delta). ✅ marks a "
        "week that's already happened — this project has no live in-week stats yet, so the delta "
        "shown is still this same projection, not real results. 📅 marks a week still ahead, "
        "projected from today's roster (it'll shift if the roster changes before then). A small "
        "delta means the bench covers it fine; a large one is worth looking for bye-week coverage "
        "via trade."
    )
    bye_impact = state["roster_bye_conflicts"]
    if bye_impact.empty:
        st.write("(none)")
    else:
        # league["settings"]["leg"] is Sleeper's current-week counter for the season - not
        # otherwise used anywhere yet, but exactly what "already happened vs. still ahead" needs.
        current_week = league["settings"].get("leg", 1)
        for _, row in bye_impact.iterrows():
            is_actual = row["week"] < current_week
            cue = "✅" if is_actual else "📅"
            label = (
                f"{cue} Week {row['week']}: {row['starters_out']} → {row['fillers']} · "
                f"{row['lineup_delta']:+.1f}"
            )
            with st.expander(label):
                if is_actual:
                    st.write(
                        "**Already happened** — no live in-week stats feed into this yet, so this "
                        "is still the same roster-based projection, not a real result."
                    )
                else:
                    st.write(
                        "**Still ahead** — projected from today's roster; will shift if the "
                        "roster changes before this week."
                    )
                st.write(f"**Starters out:** {row['starters_out']}")
                st.write(f"**Fillers:** {row['fillers']}")
                st.write(f"**Lineup delta:** {row['lineup_delta']:+.1f} vs. a full-strength week (everyone available).")
                st.write(f"**Also on bye (bench, no lineup impact):** {row['bench_out']}")

    st.subheader("Weekly gaps")
    st.caption(
        "Available (non-bye) rostered players per position per week, vs. what's needed to fill "
        "this league's dedicated starting slots (QB:1 RB:2 WR:2 TE:1). Does not account for "
        "FLEX/SUPER_FLEX, which could pull from other positions — a rough depth signal, not a "
        "full lineup-feasibility check."
    )
    weekly_gaps = state["roster_weekly_gaps"]
    gap_weeks = weekly_gaps[weekly_gaps["gap"] != ""]
    if not gap_weeks.empty:
        st.warning("Weeks with a gap:")
    show_df(gap_weeks, "No weeks have a dedicated-slot gap.")
    with st.expander("Show all 18 weeks"):
        st.dataframe(weekly_gaps, hide_index=True, width="stretch")

    st.subheader("Handcuff status")
    st.caption("Your rostered RBs who are NFL starters, and whether you also own their backup.")
    show_df(state["roster_handcuffs"], "(none of your RBs are current NFL starters)")

st.divider()
st.caption(f"Dynasty Rookie Draft · build {APP_VERSION}")
