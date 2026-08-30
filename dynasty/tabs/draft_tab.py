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
            "The whole rookie class — drafted players stay listed instead of disappearing.\n"
            "- **Rank** — value order across the whole class, drafted and undrafted together.\n"
            "- **Drafted Round / Drafted By** — blank if still undrafted.\n"
            "- **Adj. Value** — FantasyCalc's market value, corrected for this league's real "
            "scoring rules (see the Draft Plan tab's methodology); determines sort order and "
            "Rank. The only value column shown here — see the Glossary for how it relates to "
            "FantasyCalc's raw number.\n"
            "- **Tier** — FantasyCalc's own global tier across *all* players, not rookie-specific "
            "and not adjusted; gaps in the sequence are veterans/other rookies not shown here.\n"
            "- **Fits Need** — flags a currently-thin position on your roster.\n"
            "- **Handcuff To** — this rookie backs up one of your own RB starters. Expect this to "
            "be sparse pre-season: `nfl_data_py`'s player-ID crosswalk hasn't caught up with most "
            "of this year's incoming class yet — not a bug, should fill in later in the year."
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
