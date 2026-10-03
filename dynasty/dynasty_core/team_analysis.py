"""Bundled per-roster analysis view."""

from __future__ import annotations

from typing import Any

from .byes import roster_bye_conflicts, roster_weekly_gaps
from .handcuffs import roster_handcuff_status
from .lineup import lineup_breakdown, roster_capacity, weekly_lineup_breakdown
from .marginal_value import free_agent_board
from .roster_needs import (
    _need_from_phase,
    need_positions,
    positional_strength_summary,
    roster_needs_summary,
)
from .roster_value import roster_value_analysis
from .trade import sellable_players


def team_roster_analysis(
    roster: dict,
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    byes: dict[str, int],
    league: dict,
    handcuffs: dict[str, str],
    replacement_level: dict[str, float],
    available_free_agents: dict[str, dict],
    projections: dict[str, dict] | None = None,
    phase: str = "rebuilding",
) -> dict[str, Any]:
    """Every per-roster view for any team, in one call.

    `replacement_level` and `available_free_agents` are computed once per refresh and
    passed in. `phase` defaults to rebuilding. `projections` defaults to empty, giving a
    weekly lineup with no values.
    """
    roster_needs = roster_needs_summary(roster, players)
    if not roster_needs.empty:
        strength = positional_strength_summary(
            roster, players, fc_by_sleeper_id, replacement_level, league["roster_positions"]
        )
        # An outer join adds rows for positions with zero players, leaving NaN counts.
        # Recompute those so need_positions()' mask works.
        roster_needs = roster_needs.join(strength[["vor", "weak"]], how="outer")
        roster_needs["count"] = roster_needs["count"].fillna(0).astype(int)
        roster_needs["young_core"] = roster_needs["young_core"].fillna(0).astype(int)
        roster_needs["vor"] = roster_needs["vor"].fillna(0.0)
        roster_needs["weak"] = roster_needs["weak"].fillna(True)
        roster_needs["need"] = _need_from_phase(roster_needs["young_core"], roster_needs["weak"], phase)
    lineup_starters, lineup_bench, lineup_taxi, lineup_ir = lineup_breakdown(roster, players, fc_by_sleeper_id, league)
    weekly_starters, weekly_bench, weekly_taxi, weekly_ir = weekly_lineup_breakdown(
        roster, players, projections or {}, league
    )
    return {
        "roster_needs": roster_needs,
        "need_positions": need_positions(roster_needs),
        "roster_capacity": roster_capacity(roster, league),
        "roster_value": roster_value_analysis(roster, players, fc_by_sleeper_id, byes, phase=phase),
        "sellable_players": sellable_players(roster, players, fc_by_sleeper_id, replacement_level, league, byes),
        "free_agent_board": free_agent_board(available_free_agents, roster, players, fc_by_sleeper_id, byes, league),
        "roster_bye_conflicts": roster_bye_conflicts(roster, players, fc_by_sleeper_id, byes, league),
        "roster_weekly_gaps": roster_weekly_gaps(roster, players, byes, league),
        "roster_handcuffs": roster_handcuff_status(roster, players, handcuffs),
        "lineup_starters": lineup_starters,
        "lineup_bench": lineup_bench,
        "lineup_taxi": lineup_taxi,
        "lineup_ir": lineup_ir,
        "weekly_lineup_starters": weekly_starters,
        "weekly_lineup_bench": weekly_bench,
        "weekly_lineup_taxi": weekly_taxi,
        "weekly_lineup_ir": weekly_ir,
    }
