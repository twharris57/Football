"""Settings tab: which season is active, and the weeks 17/18
commissioner-announced pick deadlines (see picks_core.week_deadline) --
edited here instead of hardcoded so a year-to-year rule change is a form
edit, not a code change/redeploy.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time

import streamlit as st

import picks_core as pc
import store


def render_settings_tab(conn: sqlite3.Connection, active_season: int) -> None:
    st.subheader("Active season")
    season = int(
        st.number_input(
            "Season year", min_value=2020, max_value=2100, value=active_season, step=1, key="settings_season"
        )
    )
    if st.button("Set as active season"):
        store.set_active_season(conn, season)
        st.success(f"Active season set to {season}.")
        st.rerun()

    st.subheader(f"Weeks 17-18 deadline — {season}")
    st.caption(
        "The bylaws set an explicit early cutoff for the season's final two weeks, "
        "announced by the commissioner each year (2025: Sat Dec 27 before 1:00pm ET; "
        "Sat Jan 3 before 4:30pm ET) — earlier than either week's actual kickoffs, so "
        "it isn't derivable from the schedule. Update these once the current season's "
        "cutoffs are announced."
    )
    config = store.get_season_config(conn, season) or {}

    for week, label in ((17, "Week 17"), (18, "Week 18")):
        existing = config.get(f"week{week}_deadline")
        existing_dt = datetime.fromisoformat(existing) if existing else None
        col_date, col_time = st.columns(2)
        with col_date:
            deadline_date = st.date_input(
                f"{label} deadline date",
                value=existing_dt.date() if existing_dt else date.today(),
                key=f"week{week}_deadline_date",
            )
        with col_time:
            deadline_time = st.time_input(
                f"{label} deadline time (ET)",
                value=existing_dt.time() if existing_dt else time(13, 0),
                key=f"week{week}_deadline_time",
            )
        if st.button(f"Save {label} deadline", key=f"save_week{week}"):
            deadline = datetime.combine(deadline_date, deadline_time, tzinfo=pc.ET)
            store.set_late_season_deadline(conn, season, week, deadline)
            st.success(f"{label} deadline set to {deadline.strftime('%a %b %d, %I:%M %p ET')}.")
            st.rerun()
