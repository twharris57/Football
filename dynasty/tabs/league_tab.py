"""League tab: all-teams summary and league-wide draft pick trade values."""

from __future__ import annotations

import dynasty_core
import streamlit as st

from .components import cols, show_df


def _render_team_summary(state: dict) -> None:
    st.subheader("Team summary")
    with st.expander("How this works"):
        st.caption(
            (
                'One row per team.\n- **Total value** — summed Adj. Value.\n- **Biggest '
                "need** — the position with the lowest VOR (Roster tab's Weak signal).\n- "
                '**Open slots** — active / taxi.\n- **Phase / Rank** — the Team timeline '
                'read.'
            )
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
    summary_display = summary.sort_values("rank").copy()
    # Same win_pct format as roster_tab.py: percent, with a no-games case.
    summary_display["win_pct"] = summary_display.apply(
        lambda row: "no games played yet" if row["games_played"] == 0 else f"{row['win_pct']:.0%}",
        axis=1,
    )
    summary_display = summary_display.drop(columns="games_played")
    show_df(
        summary_display,
        "(no teams to show)",
        hide_index=True,
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
        (
            "This season's remaining picks at exact-slot value with their current "
            "owner; next season's at a flat value per round."
        )
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
