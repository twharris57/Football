"""Streamlit dashboard for the rookie draft big board (see dynasty_core/).

    streamlit run streamlit_app.py

Meant to be usable from a phone during the live draft: sidebar inputs for
league ID / username, a Refresh button (re-pulls league/rosters/draft/picks —
cheap, always live), and an "Advanced refresh" section (players/values cache
bust, plus a scoring-multiplier prewarm) — the web equivalent of the CLI's
Enter-vs-`f` prompt, split further so the slow multiplier recompute (1-2
min) is never an accidental side effect of a routine refresh, but is still
reachable from a phone if the user needs to prewarm it away from a terminal.
"""

from __future__ import annotations

import datetime as dt
import os

import dynasty_core
import requests
import streamlit as st
from tabs.components import cols, show_df, show_glossary
from tabs.draft_tab import render_draft_tab
from tabs.plan_tab import render_plan_tab
from tabs.roster_tab import render_roster_tab
from tabs.trade_tab import render_trade_tab

APP_VERSION = os.environ.get("GIT_SHA", "dev")[:7]

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
if "force_scoring_pending" not in st.session_state:
    st.session_state.force_scoring_pending = False

refresh = st.sidebar.button("Refresh")
with st.sidebar.expander("Advanced refresh"):
    st.caption(
        "Force-bust caches instead of waiting for their normal TTL. The scoring-multiplier "
        "prewarm takes 1-2 minutes (re-imports 3 seasons of weekly + play-by-play data) - do "
        "this ahead of draft day, not while on the clock."
    )
    refresh_players = st.checkbox("Players + market values (fast)", value=True)
    refresh_scoring = st.checkbox("Recompute scoring multipliers (slow, 1-2 min)")
    apply_advanced = st.button("Apply advanced refresh")

if refresh or apply_advanced:
    st.session_state.refresh_token += 1
    # A widget button/checkbox's value is only current on the exact run it
    # was clicked - any later rerun (e.g. opening an expander) can see a
    # stale/default value again. load_state's cache key must not depend on
    # that raw, one-run-only value (it did before - see PROJECT_PLAN.md),
    # or the very next rerun after a refresh click gets a different key,
    # misses cache, and silently re-fetches for no reason. These two flags
    # are durable session_state instead, stable across reruns until the
    # next actual button click changes refresh_token again.
    st.session_state.force_refresh_pending = apply_advanced and refresh_players
    st.session_state.force_scoring_pending = apply_advanced and refresh_scoring


@st.cache_data(show_spinner="Loading draft state...")
def load_state(
    league_id: str, username: str, force_full_refresh: bool, force_scoring_refresh: bool, _token: int
) -> dict:
    state = dynasty_core.gather_state(league_id, username, force_full_refresh, force_scoring_refresh)
    # Captured here, inside the cached function, so it's frozen at the
    # moment this data was actually fetched and reused verbatim on every
    # cache hit - reading dt.datetime.now() anywhere outside this function
    # would just report "now" on every rerun (tab switches, expanders),
    # not when the underlying data was last pulled.
    state["loaded_at"] = dt.datetime.now()
    return state


title_col, glossary_col = st.columns([5, 1])
with title_col:
    st.title("Dynasty Rookie Draft")
with glossary_col:
    st.write("")  # nudge the button down to roughly vertically center with the title
    if st.button("❓ Glossary", help="What VOR, power score, and other terms mean"):
        show_glossary()

try:
    state = load_state(
        league_id,
        username,
        st.session_state.force_refresh_pending,
        st.session_state.force_scoring_pending,
        st.session_state.refresh_token,
    )
except requests.RequestException as exc:
    # gather_state() names which of the two services (Sleeper/FantasyCalc)
    # actually failed.
    st.error(f"{exc}. Hit Refresh to try again.")
    st.stop()
except ValueError as exc:
    st.error(str(exc))
    st.stop()

st.sidebar.caption(
    f"Last refreshed: {state['loaded_at'].strftime('%I:%M:%S %p')} — nothing updates "
    "automatically, hit Refresh above for the latest picks."
)

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

plan_tab, lineup_tab, draft_tab, roster_tab, trade_tab = st.tabs(
    ["Draft Plan", "Lineup", "Draft Board", "Roster", "Trade Evaluator"]
)

with plan_tab:
    render_plan_tab(state)

with lineup_tab:
    st.caption(
        "Optimal current lineup by value alone — a snapshot, not week-specific yet (doesn't "
        "account for byes or injuries when deciding who starts). A by-week/injury-aware version "
        "is a planned refinement."
    )
    starter_cols = cols(
        state["lineup_starters"], ("slot", "Slot"), ("name", "Player"), ("pos", "Position"), ("adj_value", "Value")
    )
    bench_cols = cols(state["lineup_bench"], ("name", "Player"), ("pos", "Position"), ("adj_value", "Value"))
    st.subheader("Starters")
    st.dataframe(state["lineup_starters"], hide_index=True, width="stretch", column_config=starter_cols)
    st.subheader("Bench")
    show_df(state["lineup_bench"], "(empty)", column_config=bench_cols)
    st.subheader("Taxi squad")
    show_df(state["lineup_taxi"], "(empty)", column_config=bench_cols)
    st.subheader("IR / Reserve")
    show_df(state["lineup_ir"], "(empty)", column_config=bench_cols)

with draft_tab:
    render_draft_tab(state)

with roster_tab:
    render_roster_tab(state)

with trade_tab:
    render_trade_tab(state)

st.divider()
st.caption(f"Dynasty Rookie Draft · build {APP_VERSION}")
