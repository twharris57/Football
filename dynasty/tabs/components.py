"""Shared display helpers and glossary used across multiple tabs."""

from __future__ import annotations

import html
from typing import Any

import pandas as pd
import streamlit as st

# Domain jargon shown somewhere in the app without room to spell out inline
# every time (web_guidelines.md: "explain domain abbreviations on first
# use... a tooltip is acceptable in space-constrained contexts"). A "How
# this works" expander already explains VOR in full sentences right where
# it's used (Roster needs), but that requires remembering which tab/expander
# to reopen - this glossary is the one persistent, always-one-click-away
# reference instead, reachable from every tab via the header button below.
# Add a term here (not a new per-section expander) whenever the app
# introduces another acronym like this one.
GLOSSARY: dict[str, tuple[str, str]] = {
    "VOR": (
        "Value Over Replacement",
        "How much a position's actual starters exceed the value of the last "
        "startable-tier player still rostered *anywhere else* in the league "
        "at that position - an external, league-wide baseline, not just "
        "\"this player/position looks low-value.\" Negative VOR (Weak) means "
        "this position's starters don't even clear what's freely available "
        "elsewhere in the league.",
    ),
    "Power score": (
        "Team power/timeline score",
        "A continuous, league-wide score (Roster tab) combining a "
        "team's roster strength (VOR), timeline direction (value-weighted "
        "average age), and actual win percentage. 0 = league average; "
        "positive = more win-now/contending; negative = more "
        "rebuild-oriented. Recomputed fresh every refresh, so it moves with "
        "real injuries/trades/results instead of ever going stale.",
    ),
    "Adj. Value": (
        "Adjusted Value",
        "FantasyCalc's market value, corrected for this league's real "
        "scoring rules (6pt passing TDs, TE reception premium, this "
        "league's real interception/yardage rates, and more) - see the "
        "Draft Plan tab's methodology for the full correction. Shown "
        "alongside the raw, uncorrected Value for comparison, not in place "
        "of it.",
    ),
}


@st.dialog("Glossary")
def show_glossary() -> None:
    for term, (full_name, description) in GLOSSARY.items():
        st.markdown(f"**{term}** — *{full_name}*")
        st.caption(description)


def show_df(
    df: pd.DataFrame,
    empty_message: str,
    *,
    hide_index: bool = True,
    column_config: dict[str, Any] | None = None,
) -> bool:
    """Render df, or empty_message if it's empty - the repeated shape across every tab.

    Returns whether df had rows, so callers can compose extra logic (an
    extra warning, an expander) on the non-empty path. `column_config` is
    passed straight through to st.dataframe - display-only relabeling
    (see the `cols()` helper below), the underlying column names (and
    every reference to them elsewhere in this codebase) are untouched.
    """
    if df.empty:
        st.write(empty_message)
        return False
    st.dataframe(df, hide_index=hide_index, width="stretch", column_config=column_config)
    return True


def cols(df: pd.DataFrame, *specs: tuple[str, str] | tuple[str, str, str]) -> dict[str, Any]:
    """Build a column_config dict from (key, label) or (key, label, help_text) tuples.

    Human-readable table headers without renaming the underlying DataFrame
    columns everything else in this codebase (and its tests) refers to by
    their plain snake_case names. `df` is only consulted for dtypes, never
    modified - any float column (adj_value, value, avg_age, ...) gets a
    NumberColumn capped to 2 decimal digits instead of st.dataframe's
    default of showing whatever precision the underlying computation
    happened to produce (e.g. adj_value's real-scoring multiplier leaves
    values like 7827.988709). Display-only, same as the label relabeling
    itself - the DataFrame's actual values, and everything else that reads
    them, are untouched.
    """
    config: dict[str, Any] = {}
    for spec in specs:
        key, label = spec[0], spec[1]
        help_text = spec[2] if len(spec) == 3 else None
        if key in df.columns and pd.api.types.is_float_dtype(df[key]):
            config[key] = st.column_config.NumberColumn(label, help=help_text, format="%.2f")
        else:
            config[key] = st.column_config.Column(label, help=help_text)
    return config


def show_status_table(df: pd.DataFrame, empty_message: str, column_labels: dict[str, str]) -> None:
    """Render df (must have a `status_details` column, see dynasty_core.player_status_details)
    as a plain HTML table instead of st.dataframe, so each player's status icons get a real
    per-cell hover tooltip with the specific detail (e.g. the actual injury_status word).
    st.dataframe's column_config only supports a per-column tooltip (see cols()'s help text
    elsewhere), not per-cell, so this one table can't use the shared show_df approach.
    """
    if df.empty:
        st.write(empty_message)
        return

    display_cols = [c for c in df.columns if c != "status_details"]
    header_html = "".join(
        f"<th style='text-align:left; padding:4px 8px; "
        f"border-bottom:1px solid rgba(128,128,128,0.4);'>{html.escape(str(column_labels.get(c, c)))}</th>"
        for c in display_cols
    )

    body_rows = []
    for _, row in df.iterrows():
        cells = []
        for c in display_cols:
            if c == "status":
                details = row.get("status_details") or []
                cell = " ".join(f'<span title="{html.escape(desc)}">{icon}</span>' for icon, desc in details)
            else:
                value = row[c]
                if bool(pd.isna(value)):
                    cell = ""
                elif isinstance(value, float):
                    # numpy.float64 (what a pandas row actually holds) is a
                    # float subclass, so this also catches adj_value/value/bye
                    # - capped to 2 decimals same as every other table
                    # (see cols()), not whatever precision the value happens
                    # to carry (e.g. adj_value's real-scoring multiplier).
                    cell = html.escape(f"{value:.2f}")
                else:
                    cell = html.escape(str(value))
            cells.append(
                f"<td style='padding:4px 8px; border-bottom:1px solid rgba(128,128,128,0.15);'>{cell}</td>"
            )
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    table_html = (
        "<div style='overflow-x:auto;'><table style='width:100%; border-collapse:collapse; "
        f"font-size:0.9rem;'><thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table></div>"
    )
    st.markdown(table_html, unsafe_allow_html=True)


def team_selectbox(
    label: str,
    team_names: dict[int, str],
    user_roster_id: int,
    key: str,
    *,
    exclude: int | None = None,
    tag_you: bool = True,
) -> int:
    """Team-picker selectbox: the user's own team sorts first.

    `tag_you` adds a "(you)" suffix on the user's own team - left off for a
    trade-partner picker, where the real user's team could still legally
    appear in the option list (if "Your team" above was itself pointed at
    someone else) but should never be labeled as the viewer's own.
    """
    options = sorted(team_names, key=lambda rid: (rid != user_roster_id, team_names[rid]))
    if exclude is not None:
        options = [rid for rid in options if rid != exclude]

    def format_option(rid: int) -> str:
        suffix = " (you)" if tag_you and rid == user_roster_id else ""
        return team_names[rid] + suffix

    return st.selectbox(label, options, format_func=format_option, key=key)


def format_drop(drop: dict) -> str:
    """"Name (Pos)", tagged "— starter" if the drop is a current starter."""
    return f"{drop['name']} ({drop['pos']})" + (" — starter" if drop["is_starter"] else "")
