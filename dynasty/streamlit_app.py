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
from collections.abc import Callable

import dynasty_core
import requests
import streamlit as st
from tabs.components import cols, show_df, show_glossary
from tabs.draft_tab import render_draft_tab
from tabs.plan_tab import render_plan_tab
from tabs.roster_tab import render_roster_tab
from tabs.summary_tab import render_summary_tab
from tabs.trade_tab import render_trade_tab

APP_VERSION = os.environ.get("GIT_SHA", "dev")[:7]

st.set_page_config(page_title="Dynasty Rookie Draft", layout="centered")

if "league_name" not in st.session_state:
    st.session_state.league_name = "League"

st.sidebar.header(st.session_state.league_name)
league_id = st.sidebar.text_input("League ID", value=dynasty_core.DEFAULT_LEAGUE_ID)
username = st.sidebar.text_input("Username", value=dynasty_core.DEFAULT_USERNAME)

if "refresh_token" not in st.session_state:
    # "Now, rounded down to the minute" - not a fixed 0 (see below for why
    # 0 was a bug, not just a stylistic choice). Streamlit resets
    # session_state on every new/reconnected session (a page reload, a
    # phone backgrounding and reconnecting the websocket), so a session
    # that hasn't clicked Refresh yet always falls back to this default.
    # Minute-bucketing keeps the one property a shared default is for -
    # concurrent sessions loading within the same minute (e.g. two of your
    # own devices opening the page at once) still share one fetch - while
    # guaranteeing a reconnect after that window gets a real, unseen cache
    # key instead of an arbitrarily old one.
    st.session_state.refresh_token = dt.datetime.now().timestamp() // 60
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
    # A raw, full-precision timestamp - not an incrementing counter, and not
    # bucketed like the pre-click default above. st.cache_data's cache is
    # shared across the whole server process, not per-session; a click is a
    # deliberate "get me current data now," so its key must be unique enough
    # to never collide with any prior click's value or a stale default
    # bucket. A counter restarting at 0 on each new session could land on a
    # small integer some *other* session already used earlier in the draft,
    # silently hitting that session's stale cached snapshot instead of
    # re-fetching (found live, 2026-08-08). A sub-second timestamp can't
    # collide that way.
    st.session_state.refresh_token = dt.datetime.now().timestamp()
    # A widget button/checkbox's value is only current on the exact run it
    # was clicked - any later rerun (e.g. opening an expander) can see a
    # stale/default value again. load_state's cache key must not depend on
    # that raw, one-run-only value (it did before - see PROJECT_PLAN_DYNASTY.md),
    # or the very next rerun after a refresh click gets a different key,
    # misses cache, and silently re-fetches for no reason. These two flags
    # are durable session_state instead, stable across reruns until the
    # next actual button click changes refresh_token again.
    st.session_state.force_refresh_pending = apply_advanced and refresh_players
    st.session_state.force_scoring_pending = apply_advanced and refresh_scoring


@st.cache_data(show_spinner="Loading draft state...", ttl="1h")
# ttl is a backstop, not the primary freshness mechanism (that's the minute-
# bucketed default token above) - without it, a NAS deployment that stays up
# for a whole multi-week draft would accumulate one cache entry per distinct
# minute bucket / click forever, since st.cache_data never evicts on its own
# with no ttl set.
def load_state(
    league_id: str, username: str, force_full_refresh: bool, force_scoring_refresh: bool, token: float
) -> dict:
    # `token` must NOT be named `_token` (or any other leading-underscore
    # name) - Streamlit's st.cache_data silently excludes any argument whose
    # name starts with "_" from the cache key entirely (verified directly
    # against the installed streamlit source, 2026-08-16). A prior version of
    # this parameter was named `_token`, which meant its value never actually
    # affected caching - a plain Refresh click looked like it was cache-busting
    # (the button, the session_state write, the spinner all "worked") but
    # silently kept returning whatever was cached under the first-ever
    # (league_id, username, force_full_refresh, force_scoring_refresh) call in
    # the process's lifetime. This is the actual root cause of the "Refresh
    # doesn't pick up new picks" bug two earlier fixes (see PROJECT_PLAN_DYNASTY.md)
    # attempted and failed to fix, since both only changed the *value* being
    # passed in, never the fact that the name made the value irrelevant.
    state = dynasty_core.gather_state(league_id, username, force_full_refresh, force_scoring_refresh)
    # Captured here, inside the cached function, so it's frozen at the
    # moment this data was actually fetched and reused verbatim on every
    # cache hit - reading dt.datetime.now() anywhere outside this function
    # would just report "now" on every rerun (tab switches, expanders),
    # not when the underlying data was last pulled.
    state["loaded_at"] = dt.datetime.now()
    # A cheap, already-unique identity for "this particular fetch" - token is
    # only ever a fresh, real timestamp on a genuine refetch (see above), so
    # it doubles as a version stamp any on-demand, session_state-cached UI
    # result can carry alongside itself and compare against later, to detect
    # "this was computed against an earlier state" rather than silently
    # displaying it as current (see trade_tab.py's suggested-trades scan for
    # the first consumer of this, docs/dynasty-data-model.md for the pattern).
    state["version"] = token
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


def _render_lineup_tab() -> None:
    mode = st.radio(
        "Ranking",
        ["By value (dynasty)", f"This week's projection (Week {state['projection_week']})"],
        horizontal=True,
        key="lineup_tab_mode",
    )
    if mode == "By value (dynasty)":
        st.caption(
            "Optimal lineup by long-run dynasty trade value — the same ranking trade, drop, and "
            "draft-plan decisions use elsewhere in this app. Doesn't account for byes or injuries "
            "when deciding who starts; switch to the other mode for a this-week points view instead."
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
                "This week's player projections are unavailable this refresh — see the warning "
                "above. Try the \"By value\" mode instead, or hit Refresh to retry."
            )
            return
        st.caption(
            "Optimal lineup by this week's projected points — Sleeper's own weekly per-player "
            "projections, scored against this league's real scoring settings. A different question "
            "than dynasty value: who wins you the most points this week, not who's the better "
            "long-run asset (trade/drop decisions still use the value-based mode)."
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


# Tab order shifts with the season rather than staying fixed: Draft Plan is
# the tab checked right before a live pick (see NB-2), so it leads while a
# draft is ongoing/upcoming; Summary is more useful once the draft is behind
# you, so it leads instead once draft_complete (same condition already
# driving the "Draft complete."/on-the-clock banner above - both "before any
# picks" and "mid-draft" fall under draft_complete=False, exactly the
# "ongoing/upcoming" grouping this is meant to capture).
tab_specs: list[tuple[str, Callable[[], None]]] = [
    ("Draft Plan", lambda: render_plan_tab(state)),
    ("Lineup", _render_lineup_tab),
    ("Draft Board", lambda: render_draft_tab(state)),
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
st.caption(f"Dynasty Rookie Draft · build {APP_VERSION}")
