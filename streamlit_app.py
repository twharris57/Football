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

st.subheader("Your picks")
if state["your_picks"].empty:
    st.write("(none)")
else:
    st.dataframe(state["your_picks"], hide_index=True, width="stretch")

st.subheader("Roster capacity")
cap = state["roster_capacity"]
cap_col1, cap_col2 = st.columns(2)
cap_col1.metric("Active roster", f"{cap['active_filled']}/{cap['active_total']}", f"{cap['active_open']} open")
cap_col2.metric("Taxi squad", f"{cap['taxi_filled']}/{cap['taxi_total']}", f"{cap['taxi_open']} open")
if cap["active_open"] <= 0 and cap["taxi_open"] <= 0:
    st.warning("No open roster or taxi slots — drafting a rookie means dropping someone first.")

st.subheader("Your roster needs")
if state["roster_needs"].empty:
    st.write("(empty roster)")
else:
    st.dataframe(state["roster_needs"], width="stretch")
needs = state["need_positions"]
if needs:
    st.info(f"Flagged needs: {', '.join(sorted(needs))} — the big board below marks rookies at these positions.")
else:
    st.info("No positions are flagged as a need right now — best available value is the main signal.")

if not state["recent_picks"].empty:
    st.subheader("Recently drafted")
    st.dataframe(state["recent_picks"], hide_index=True, width="stretch")

st.subheader("Available rookies (big board)")
st.caption(
    "**tier** is FantasyCalc's global dynasty tier across *all* players, not rookie-specific — "
    "gaps in the sequence are veterans/other rookies not shown here, lower is better. "
    "**rank** is this player's order within available rookies only. "
    "**fits_need** flags a currently-thin position on your roster."
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
