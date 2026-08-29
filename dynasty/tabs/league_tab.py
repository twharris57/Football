"""League tab: all-teams summary and league-wide draft pick trade values."""

from __future__ import annotations

import dynasty_core
import streamlit as st

from .components import cols, show_df


def _render_team_summary(state: dict) -> None:
    st.subheader("Team summary")
    with st.expander("How this works"):
        st.caption(
            "One row per team, at a glance.\n"
            "- **Total value** — sum of Adj. Value (real-scoring-corrected market value) "
            "across the whole roster, same numbers the Roster tab shows per player.\n"
            "- **Biggest need** — the position with the lowest VOR (value-over-replacement, "
            "see the Glossary above) on that roster — the same signal driving the Roster "
            "tab's own \"Weak\" flag, not a separate metric.\n"
            "- **Open slots** — active roster / taxi squad openings.\n"
            "- **Phase / Rank** — the same power/timeline read as the Roster tab's Team "
            "timeline section, for every team side by side."
        )
    summary = dynasty_core.league_team_summaries(
        state["rosters_by_id"],
        state["players"],
        state["fc_by_sleeper_id"],
        state["byes"],
        state["league"],
        state["replacement_level"],
        state["team_names"],
        state["team_power_timeline"],
    )
    summary_display = summary.sort_values("rank")
    show_df(
        summary_display,
        "(no teams to show)",
        hide_index=False,
        column_config=cols(
            summary_display,
            ("team", "Team"),
            ("total_value", "Total Value"),
            ("biggest_need", "Biggest Need"),
            ("active_open", "Active Open"),
            ("taxi_open", "Taxi Open"),
            ("phase", "Phase"),
            ("rank", "Power Rank"),
            ("win_pct", "Win %"),
        ),
    )


def _render_pick_values(state: dict) -> None:
    st.subheader("Draft pick trade values")
    st.caption(
        "Every remaining pick this season, exact-slot valued and matched to its real "
        "current owner, plus next season's picks at a flat round value applied the same "
        "to every team (no real projected standings this far out to justify guessing who "
        "picks early vs. late)."
    )
    pick_values_display = state["pick_trade_values"].drop(columns="owner_roster_id", errors="ignore")
    show_df(
        pick_values_display,
        "(no picks to show)",
        column_config=cols(pick_values_display, ("pick", "Pick"), ("owner", "Owner"), ("value", "Value")),
    )


def render_league_tab(state: dict) -> None:
    _render_team_summary(state)
    _render_pick_values(state)
