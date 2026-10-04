"""Shared display helpers and glossary used across multiple tabs."""

from __future__ import annotations

import html
from typing import Any

import pandas as pd
import streamlit as st

# Jargon defined once, reachable from every tab. Add new acronyms here.
GLOSSARY: dict[str, tuple[str, str]] = {
    "VOR": (
        "Value Over Replacement",
        "How much a position's starters are worth above the league-wide replacement "
        "level (the last startable player rostered anywhere). Zero or below is Weak.",
    ),
    "Power score": (
        "Team power/timeline score",
        "League-relative blend of roster strength (VOR), value-weighted age, and "
        "record. 0 is average; positive leans contending. Updates every refresh.",
    ),
    "Adj. Value": (
        "Adjusted Value",
        "FantasyCalc's market value corrected for this league's scoring (6pt pass TDs, "
        "TE premium, INT and yardage rates, bonuses). Raw Value is shown beside it where "
        "both appear.",
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
    """Render `df` or `empty_message`; returns whether `df` had rows."""
    if df.empty:
        st.write(empty_message)
        return False
    st.dataframe(df, hide_index=hide_index, width="stretch", column_config=column_config)
    return True


def cols(df: pd.DataFrame, *specs: tuple[str, str] | tuple[str, str, str]) -> dict[str, Any]:
    """Build a `column_config` from `(key, label[, help])` tuples; floats show 2 decimals."""
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
    """Render `df` as HTML so status icons get per-cell tooltips (`st.dataframe` can't)."""
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
                    # numpy.float64 is a float subclass: cap to 2 decimals like cols().
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
    """Team picker with the user's team first; `tag_you` adds "(you)" (off for partner pickers)."""
    options = sorted(team_names, key=lambda rid: (rid != user_roster_id, team_names[rid]))
    if exclude is not None:
        options = [rid for rid in options if rid != exclude]

    def format_option(rid: int) -> str:
        suffix = " (you)" if tag_you and rid == user_roster_id else ""
        return team_names[rid] + suffix

    return st.selectbox(label, options, format_func=format_option, key=key)


def format_drop(drop: dict) -> str:
    """"Name (Pos, value: X)", tagged "— starter" if the drop is a current starter."""
    value = drop.get("adj_value")
    value_str = f", value: {value:.0f}" if value is not None else ""
    return f"{drop['name']} ({drop['pos']}{value_str})" + (" — starter" if drop["is_starter"] else "")
