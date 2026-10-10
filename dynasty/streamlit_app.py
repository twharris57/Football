"""Dynasty league dashboard, built for use from a phone during a live draft.

    streamlit run streamlit_app.py
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Callable
from pathlib import Path

import dynasty_core
import requests
import streamlit as st
from tabs.components import cols, show_df, show_glossary
from tabs.draft_tab import render_draft_tab
from tabs.league_tab import render_league_tab
from tabs.plan_tab import render_plan_tab
from tabs.roster_tab import render_roster_tab
from tabs.summary_tab import render_summary_tab
from tabs.trade_tab import render_trade_tab

APP_VERSION = os.environ.get("GIT_SHA", "dev")[:7]
APP_SEMVER = (Path(__file__).parent / "VERSION").read_text().strip()

st.set_page_config(page_title="Fantasy Tools", layout="centered")

if "league_name" not in st.session_state:
    st.session_state.league_name = "League"

st.sidebar.header(st.session_state.league_name)
league_id = st.sidebar.text_input("League ID", value=dynasty_core.DEFAULT_LEAGUE_ID)
username = st.sidebar.text_input("Username", value=dynasty_core.DEFAULT_USERNAME)

if "refresh_token" not in st.session_state:
    # Before any click: the current minute, so sessions opened together share one fetch
    # and reconnects later get a fresh key.
    st.session_state.refresh_token = dt.datetime.now().timestamp() // 60
if "force_refresh_pending" not in st.session_state:
    st.session_state.force_refresh_pending = False
if "force_scoring_pending" not in st.session_state:
    st.session_state.force_scoring_pending = False

refresh = st.sidebar.button("Refresh")
with st.sidebar.expander("Advanced refresh"):
    st.caption(
        (
            'Bypass caches now. Recomputing scoring multipliers takes 1-2 minutes; do '
            'it before draft day, not on the clock.'
        )
    )
    refresh_players = st.checkbox("Players + market values (fast)", value=True)
    refresh_scoring = st.checkbox("Recompute scoring multipliers (slow, 1-2 min)")
    apply_advanced = st.button("Apply advanced refresh")

if refresh or apply_advanced:
    # A full timestamp: the cache is shared across sessions, so a click's key must never
    # repeat an earlier one.
    st.session_state.refresh_token = dt.datetime.now().timestamp()
    # Button values only last one run; persist the flags so later reruns keep the same key.
    st.session_state.force_refresh_pending = apply_advanced and refresh_players
    st.session_state.force_scoring_pending = apply_advanced and refresh_scoring


@st.cache_data(show_spinner="Loading draft state...", ttl="1h")
# ttl only bounds cache growth on a long-running server.
def load_state(
    league_id: str, username: str, force_full_refresh: bool, force_scoring_refresh: bool, token: float
) -> dict:
    # Must not start with "_": st.cache_data leaves underscore args out of the key,
    # which would make Refresh a no-op. Guarded by test_streamlit_refresh_cache.py.
    state = dynasty_core.gather_state(league_id, username, force_full_refresh, force_scoring_refresh)
    # Stamped inside the cached function so it shows fetch time, not rerun time.
    state["loaded_at"] = dt.datetime.now()
    # Version stamp for on-demand results cached in session_state.
    state["version"] = token
    return state


title_col, glossary_col = st.columns([5, 1])
with title_col:
    st.title("Fantasy Tools")
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


def _render_lineup_tab() -> None:
    mode = st.radio(
        "Ranking",
        ["By value (dynasty)", f"This week's projection (Week {state['projection_week']})"],
        horizontal=True,
        key="lineup_tab_mode",
    )
    if mode == "By value (dynasty)":
        st.caption(
            (
                'Best lineup by dynasty value, the value trade and drop decisions use. '
                'Ignores byes and injuries.'
            )
        )
        starters, bench, taxi, ir = (
            state["lineup_starters"],
            state["lineup_bench"],
            state["lineup_taxi"],
            state["lineup_ir"],
        )
        value_label = "Value"
    else:
        if not state["projections"]:
            st.info(
                (
                    'This week\'s projections are unavailable (see the warning above). Use "By '
                    'value" or Refresh to retry.'
                )
            )
            return
        st.caption(
            (
                "Best lineup by this week's Sleeper projections, scored with this league's "
                'settings. For start/sit, not trade value.'
            )
        )
        starters, bench, taxi, ir = (
            state["weekly_lineup_starters"],
            state["weekly_lineup_bench"],
            state["weekly_lineup_taxi"],
            state["weekly_lineup_ir"],
        )
        value_label = "Proj. Pts"

    starter_cols = cols(starters, ("slot", "Slot"), ("name", "Player"), ("pos", "Position"), ("adj_value", value_label))
    bench_cols = cols(bench, ("name", "Player"), ("pos", "Position"), ("adj_value", value_label))
    st.subheader("Starters")
    st.dataframe(starters, hide_index=True, width="stretch", column_config=starter_cols)
    st.subheader("Bench")
    show_df(bench, "(empty)", column_config=bench_cols)
    st.subheader("Taxi squad")
    show_df(taxi, "(empty)", column_config=bench_cols)
    st.subheader("IR / Reserve")
    show_df(ir, "(empty)", column_config=bench_cols)


# Draft Plan leads during a draft; Summary leads once it's complete.
tab_specs: list[tuple[str, Callable[[], None]]] = [
    ("Draft Plan", lambda: render_plan_tab(state)),
    ("Lineup", _render_lineup_tab),
    ("Draft Board", lambda: render_draft_tab(state)),
    ("League", lambda: render_league_tab(state)),
    ("Roster", lambda: render_roster_tab(state)),
    ("Trade Evaluator", lambda: render_trade_tab(state)),
    ("Summary", lambda: render_summary_tab(state)),
]
draft_complete = current_pick_no > total_picks
if draft_complete:
    tab_specs.insert(0, tab_specs.pop())

tabs = st.tabs([label for label, _ in tab_specs])
for tab, (_, render_fn) in zip(tabs, tab_specs):
    with tab:
        render_fn()

st.divider()
st.caption(f"Fantasy Tools · v{APP_SEMVER} · build {APP_VERSION}")
