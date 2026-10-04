"""Draft Board tab: the user's picks, recently drafted players, and the rookie big board."""

from __future__ import annotations

import streamlit as st

from .components import cols, show_df


def render_draft_tab(state: dict) -> None:
    st.subheader("Your picks")
    show_df(
        state["your_picks"],
        "(none)",
        column_config=cols(
            state["your_picks"],
            ("round", "Round"),
            ("overall_pick", "Pick #"),
            ("status", "Status"),
            ("acquired_from", "Acquired From"),
        ),
    )

    if not state["recent_picks"].empty:
        st.subheader("Recently drafted")
        st.dataframe(
            state["recent_picks"],
            hide_index=True,
            width="stretch",
            column_config=cols(
                state["recent_picks"], ("pick", "Pick #"), ("team", "Team"), ("player", "Player"), ("pos", "Position")
            ),
        )

    st.subheader("Rookie big board")
    with st.expander("How this works"):
        st.caption(
            (
                'The whole rookie class; drafted players stay listed.\n- **Rank** — by Adj. '
                'Value across the class.\n- **Drafted Round / By** — blank if still '
                'available.\n- **Adj. Value** — FantasyCalc value corrected for this '
                "league's scoring (see the Glossary).\n- **Tier** — FantasyCalc's tier "
                'across all players, so gaps are normal.\n- **Fits Need** — a thin position '
                'on your roster.\n- **Handcuff To** — backs up one of your RB starters. '
                'Sparse before the season, until the ID crosswalk catches up.'
            )
        )
    board = state["big_board"]
    if board.empty:
        st.write("(no rookies available)")
    else:
        board_cols = cols(
            board,
            ("rank", "Rank"),
            ("name", "Player"),
            ("pos", "Position"),
            ("fits_need", "Fits Need"),
            ("handcuff_to", "Handcuff To"),
            ("drafted_round", "Drafted Round"),
            ("drafted_by", "Drafted By"),
            ("team", "Team"),
            ("college", "College"),
            ("age", "Age"),
            ("adj_value", "Adj. Value"),
        )
        for tier in sorted(board["tier"].unique()):
            st.markdown(f"**Tier {tier}**")
            st.dataframe(
                board[board["tier"] == tier].drop(columns="tier"),
                hide_index=True,
                width="stretch",
                column_config=board_cols,
            )
