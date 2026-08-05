"""Bundled per-roster analysis view."""

from __future__ import annotations

from typing import Any

from .byes import roster_bye_conflicts, roster_weekly_gaps
from .constants import YOUNG_CORE_NEED_THRESHOLD
from .handcuffs import roster_handcuff_status
from .lineup import lineup_breakdown, roster_capacity
from .marginal_value import free_agent_board
from .roster_needs import (
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
) -> dict[str, Any]:
    """Bundle every per-roster analysis view into one call, for any team's roster.

    Every function it calls already takes a generic `roster` dict — this is
    the one code path both `gather_state`'s own user-roster computation and
    the Roster tab's team selector use, rather than a second,
    roster-agnostic model. `roster_needs` joins `roster_needs_summary`'s
    young-core `need` flag and `positional_strength_summary`'s
    value-over-replacement `weak` flag on position — two different
    questions about the same position. `replacement_level` is the
    league-wide baseline computed once per refresh (`position_replacement_levels`)
    and passed in, not recomputed here. `available_free_agents`
    (`free_agent_pool()`'s output) is likewise computed once per refresh and
    passed in, not recomputed per team looked up through the team selector.
    """
    roster_needs = roster_needs_summary(roster, players)
    if not roster_needs.empty:
        strength = positional_strength_summary(
            roster, players, fc_by_sleeper_id, replacement_level, league["roster_positions"]
        )
        # strength always covers all 4 FANTASY_POSITIONS (see
        # positional_strength_summary), but roster_needs only has rows for
        # positions the roster actually has a player at - an outer join adds
        # a real, meaningful row for "zero players at this position" (should
        # absolutely show up as both a need and weak), but leaves count/
        # young_core/need as NaN for it, which breaks need_positions()'s
        # boolean mask below. Recompute them post-join instead of trusting
        # the NaN default.
        roster_needs = roster_needs.join(strength[["vor", "weak"]], how="outer")
        roster_needs["count"] = roster_needs["count"].fillna(0).astype(int)
        roster_needs["young_core"] = roster_needs["young_core"].fillna(0).astype(int)
        roster_needs["need"] = roster_needs["young_core"] < YOUNG_CORE_NEED_THRESHOLD
        roster_needs["vor"] = roster_needs["vor"].fillna(0.0)
        roster_needs["weak"] = roster_needs["weak"].fillna(True)
    lineup_starters, lineup_bench, lineup_taxi, lineup_ir = lineup_breakdown(roster, players, fc_by_sleeper_id, league)
    return {
        "roster_needs": roster_needs,
        "need_positions": need_positions(roster_needs),
        "roster_capacity": roster_capacity(roster, league),
        "roster_value": roster_value_analysis(roster, players, fc_by_sleeper_id, byes),
        "sellable_players": sellable_players(roster, players, fc_by_sleeper_id, replacement_level, league, byes),
        "free_agent_board": free_agent_board(available_free_agents, roster, players, fc_by_sleeper_id, byes, league),
        "roster_bye_conflicts": roster_bye_conflicts(roster, players, fc_by_sleeper_id, byes, league),
        "roster_weekly_gaps": roster_weekly_gaps(roster, players, byes, league),
        "roster_handcuffs": roster_handcuff_status(roster, players, handcuffs),
        "lineup_starters": lineup_starters,
        "lineup_bench": lineup_bench,
        "lineup_taxi": lineup_taxi,
        "lineup_ir": lineup_ir,
    }
