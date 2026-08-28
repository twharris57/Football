"""Settings tab: which season is active, and the late-season
commissioner-announced pick deadlines (see picks_core.week_deadline;
which weeks these apply to is store.KNOWN_LATE_SEASON_WEEKS, since that
set itself changes year to year) -- edited here instead of hardcoded so a
year-to-year rule change is a form edit, not a code change/redeploy.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time

import streamlit as st

import picks_core as pc
import store

# The real 2026 Legion Pool late-season deadlines, confirmed against the
# actual commissioner-issued rules document (2026-08-27). Used only as this
# season's starting default for an unconfigured week -- so a first visit to
# this tab after deploying is "review and save," not "look these up and
# retype them." A real season_week_rules row, once saved, always overrides
# this. Update (or drop) once a season's real dates change.
KNOWN_2026_LATE_SEASON_DEADLINES: dict[int, datetime] = {
    16: datetime(2026, 12, 26, 13, 0, tzinfo=pc.ET),
    17: datetime(2027, 1, 2, 16, 30, tzinfo=pc.ET),
    18: datetime(2027, 1, 9, 16, 30, tzinfo=pc.ET),
}


def render_settings_tab(conn: sqlite3.Connection, active_season: int, today: date) -> None:
    with st.expander("Active season", expanded=False):
        st.write(f"Current season: **{active_season}**")
        next_season = active_season + 1
        season_open = pc.default_season_year(today) >= next_season
        if st.button(f"Open {next_season} season", disabled=not season_open):
            store.set_active_season(conn, next_season)
            st.success(f"Active season set to {next_season}.")
            st.rerun()
        if not season_open:
            st.caption(f"Available once the {active_season} season has ended.")

    late_weeks = store.KNOWN_LATE_SEASON_WEEKS
    with st.expander(f"Weeks {late_weeks[0]}-{late_weeks[-1]} deadline — {active_season}", expanded=False):
        st.caption(
            "The bylaws set an explicit early cutoff for the season's final few weeks, "
            "announced by the commissioner each year — earlier than any of that week's "
            "actual kickoffs, so it isn't derivable from the schedule. The fields below "
            "default to the real announced values once known (currently: 2026 season); "
            "update them once a season's actual cutoffs are announced or change. *Which* "
            "weeks this covers can also change year to year (2025 was just weeks 17-18; "
            "2026 added week 16) — if a week that needs this isn't listed below, see "
            "`store.KNOWN_LATE_SEASON_WEEKS`."
        )
        for week in late_weeks:
            label = f"Week {week}"
            week_rule = store.get_week_rule(conn, active_season, week)
            existing = week_rule.get("deadline_override") if week_rule else None
            existing_dt = datetime.fromisoformat(existing) if existing else None
            known_default = KNOWN_2026_LATE_SEASON_DEADLINES.get(week) if active_season == 2026 else None
            default_dt = existing_dt or known_default
            col_date, col_time = st.columns(2)
            with col_date:
                deadline_date = st.date_input(
                    f"{label} deadline date",
                    value=default_dt.date() if default_dt else date.today(),
                    key=f"week{week}_deadline_date",
                )
            with col_time:
                deadline_time = st.time_input(
                    f"{label} deadline time (ET)",
                    value=default_dt.time() if default_dt else time(13, 0),
                    key=f"week{week}_deadline_time",
                )
            if st.button(f"Save {label} deadline", key=f"save_week{week}"):
                deadline = datetime.combine(deadline_date, deadline_time, tzinfo=pc.ET)
                store.set_late_season_deadline(conn, active_season, week, deadline)
                st.success(f"{label} deadline set to {deadline.strftime('%a %b %d, %I:%M %p ET')}.")
                st.rerun()

    with st.expander("Team display names", expanded=False):
        st.caption(
            "The Legion pool's own pick sheet doesn't use nfl_data_py's raw team "
            "abbreviations (e.g. `LAC`) — these overrides control what's shown "
            "instead on the Picks tab. Purely a display label; doesn't affect "
            "ranking or scoring."
        )
        team_names = store.get_team_display_names(conn)
        edited: dict[str, str] = {}
        cols = st.columns(4)
        for i, abbr in enumerate(pc.NFL_TEAM_ABBREVIATIONS):
            with cols[i % 4]:
                edited[abbr] = st.text_input(
                    abbr, value=team_names.get(abbr, abbr), key=f"team_name_{abbr}"
                )
        if st.button("Save team display names"):
            for abbr, name in edited.items():
                name = name.strip()
                if name:
                    store.set_team_display_name(conn, abbr, name)
            st.success("Team display names saved.")
            st.rerun()
