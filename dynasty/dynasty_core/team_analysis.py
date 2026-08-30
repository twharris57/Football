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
    """Bundle every per-roster analysis view into one call, for any team's roster.

    Every function it calls already takes a generic `roster` dict — this is
    the one code path both `gather_state`'s own user-roster computation and
    the Roster tab's team selector use, rather than a second,
    roster-agnostic model. `roster_needs` joins `roster_needs_summary`'s
    young-core count and `positional_strength_summary`'s
    value-over-replacement `weak` flag on position — two different
    questions about the same position, always shown side by side regardless
    of phase. `need` itself, however, is phase-aware
    (`_need_from_phase()`): young-core accumulation while `phase ==
    "rebuilding"`, the same `weak` roster-hole read otherwise - see
    `docs/rookie-draft-big-board.md`'s "Roster needs" section.
    `replacement_level` is the league-wide baseline computed once per
    refresh (`position_replacement_levels`) and passed in, not recomputed
    here. `available_free_agents` (`free_agent_pool()`'s output) is
    likewise computed once per refresh and passed in, not recomputed per
    team looked up through the team selector. `phase` (this roster's own
    rebuilding/treading_water/contending label from
    `team_power_timeline_scores()`) defaults to `"rebuilding"` for a caller
    without one handy - the original, single-rule behavior. `projections`
    (this week's per-player point projections) defaults
    to `{}` — only the Lineup tab's own team actually renders
    `weekly_lineup_*`, so a caller that doesn't have (or care about) this
    week's projections, like the Roster tab's other-team lookup, can omit
    it and just get an all-`None`-value weekly lineup back, the same
    graceful-degradation shape a failed fetch already produces.
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
