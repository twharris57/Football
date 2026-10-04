"""Attention digest: a short "what needs a look right now" list from existing signals."""

from __future__ import annotations

import pandas as pd


def build_attention_digest(
    need_positions: frozenset[str],
    roster_weekly_gaps: pd.DataFrame,
    sellable_players: pd.DataFrame,
    free_agent_board: pd.DataFrame,
    pickup_alerts: list[dict],
    current_week: int,
    *,
    top_n: int = 3,
) -> dict[str, list[str]]:
    """Format and cap already-ranked signals into short digest lists with "(+N more)" notes.

    Weekly gaps before `current_week` are dropped before capping. `pickup_alerts` must
    arrive ranked and filtered.
    """
    digest: dict[str, list[str]] = {
        "needs": [f"Flagged needs: {', '.join(sorted(need_positions))}"] if need_positions else [],
        "weekly_gaps": _capped(_weekly_gap_lines(roster_weekly_gaps, current_week), top_n),
        "sellable": _capped(_sellable_lines(sellable_players), top_n),
        "free_agents": _capped(_free_agent_lines(free_agent_board), top_n),
        "pickup_alerts": _capped(_pickup_alert_lines(pickup_alerts), top_n),
    }
    return digest


def _weekly_gap_lines(roster_weekly_gaps: pd.DataFrame, current_week: int) -> list[str]:
    gap_rows = roster_weekly_gaps[
        (roster_weekly_gaps["gap"] != "") & (roster_weekly_gaps["week"] >= current_week)
    ]
    return [f"Week {row['week']}: gap at {row['gap']}" for _, row in gap_rows.iterrows()]


def _sellable_lines(sellable_players: pd.DataFrame) -> list[str]:
    lines = []
    for _, row in sellable_players.iterrows():
        value_str = f"{row['adj_value']:.0f}" if pd.notna(row["adj_value"]) else "unknown"
        lines.append(f"{row['name']} ({row['pos']}, value: {value_str})")
    return lines


def _impact_and_drop_note(marginal_value: float, drop_name: str | None, drop_is_starter: bool | None) -> str:
    """"would add +X to your lineup[ — would require dropping Y (a starter)]", shared by free agents and pickup alerts."""
    note = f"would add {marginal_value:+.1f} to your lineup"
    if pd.notna(drop_name):
        starter_note = " (a starter)" if drop_is_starter else ""
        note += f" — would require dropping {drop_name}{starter_note}"
    return note


def _free_agent_lines(free_agent_board: pd.DataFrame) -> list[str]:
    if free_agent_board.empty:
        # An empty board has no columns, so filtering by column name would raise.
        return []
    positive = free_agent_board[free_agent_board["marginal_value"] > 0]
    return [
        f"{row['name']} ({row['pos']}) {_impact_and_drop_note(row['marginal_value'], row['drop_name'], row['drop_is_starter'])}"
        for _, row in positive.iterrows()
    ]


def _pickup_alert_lines(pickup_alerts: list[dict]) -> list[str]:
    lines = []
    for alert in pickup_alerts:
        kind = alert["kind"]
        if kind == "team" and alert["old"] is None:
            base = f"{alert['name']} ({alert['pos']}) just signed with {alert['new']}"
        elif kind == "team":
            base = f"{alert['name']} ({alert['pos']}) changed teams: {alert['old']} → {alert['new']}"
        elif kind == "depth_chart":
            base = (
                f"{alert['name']} ({alert['pos']}, {alert['team']}) depth chart order "
                f"improved: {alert['old']} → {alert['new']}"
            )
        else:  # "status"
            base = f"{alert['name']} ({alert['pos']}, {alert['team']}) status changed: {alert['old']} → {alert['new']}"
        note = _impact_and_drop_note(alert["marginal_value"], alert.get("drop_name"), alert.get("drop_is_starter"))
        lines.append(f"{base} — {note}")
    return lines


def _capped(lines: list[str], top_n: int) -> list[str]:
    """Cap `lines` to `top_n`, appending a "(+N more)" note if any were dropped."""
    if len(lines) <= top_n:
        return lines
    return lines[:top_n] + [f"(+{len(lines) - top_n} more)"]
