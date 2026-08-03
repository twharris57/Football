"""Positional value, replacement level, and roster-needs signals."""

from __future__ import annotations

import pandas as pd

from .constants import FANTASY_POSITIONS, YOUNG_CORE_NEED_THRESHOLD
from .player_pools import roster_fantasy_players

YOUNG_CORE_MAX_YOE = 2


def roster_needs_summary(roster: dict, players: dict[str, dict]) -> pd.DataFrame:
    """Summarize the roster by position: depth, average age, and young-core count.

    `need` flags a position where fewer than YOUNG_CORE_NEED_THRESHOLD players
    have YOUNG_CORE_MAX_YOE years of experience or less — a rough signal for
    where a rebuild still needs young talent, not a full needs model.
    """
    rows = [
        {"pos": info.get("position"), "age": info.get("age"), "years_exp": info.get("years_exp")}
        for _player_id, info in roster_fantasy_players(roster, players)
    ]

    roster_df = pd.DataFrame(rows)
    if roster_df.empty:
        return roster_df

    summary = roster_df.groupby("pos").agg(
        count=("pos", "count"),
        avg_age=("age", "mean"),
        young_core=("years_exp", lambda s: int((s <= YOUNG_CORE_MAX_YOE).sum())),
    )
    summary = summary.reindex(FANTASY_POSITIONS).dropna(how="all")
    summary["need"] = summary["young_core"] < YOUNG_CORE_NEED_THRESHOLD
    return summary.round(1)


def need_positions(roster_needs: pd.DataFrame) -> frozenset[str]:
    """Return the set of positions currently flagged as a roster need."""
    if roster_needs.empty:
        return frozenset()
    return frozenset(roster_needs.index[roster_needs["need"]])


def _position_starter_demand(position: str, roster_positions: list[str]) -> int:
    """How many players are really demanded at a position: dedicated slots, plus
    SUPER_FLEX demand for QB specifically (matching the market-value call's own
    `num_qbs`), since roughly two QBs per team are startable in this superflex
    league, not one. FLEX demand for RB/WR/TE is deliberately not modeled — see
    `.claude/conventions/valuation_principles.md`'s "superflex inflates QB value"
    rule and docs/rookie-draft-big-board.md's "Roster needs" section.
    """
    count = roster_positions.count(position)
    if position == "QB":
        count += roster_positions.count("SUPER_FLEX")
    return max(count, 1)


def position_replacement_levels(
    rosters: list[dict], players: dict[str, dict], fc_by_sleeper_id: dict[str, dict], roster_positions: list[str]
) -> dict[str, float]:
    """League-wide replacement-level adj_value per position — the value of the
    Nth-best rostered player at that position across the whole league, where
    N = `_position_starter_demand()` times the number of teams. Every
    rostered player counts toward the pool (including taxi/IR — they're not
    on waivers). An external baseline rather than a same-roster-relative
    metric deliberately, so one elite player elsewhere can't distort another
    position's apparent strength. See docs/rookie-draft-big-board.md's
    "Roster needs" section for the full rationale.
    """
    pools: dict[str, list[float]] = {pos: [] for pos in FANTASY_POSITIONS}
    for roster in rosters:
        for player_id in roster.get("players") or []:
            position = players.get(player_id, {}).get("position")
            if position not in FANTASY_POSITIONS:
                continue
            entry = fc_by_sleeper_id.get(player_id)
            adj_value = entry.get("adj_value") if entry else None
            pools[position].append(adj_value if adj_value is not None else 0.0)

    num_teams = len(rosters)
    replacement_level: dict[str, float] = {}
    for position in FANTASY_POSITIONS:
        pool = sorted(pools[position], reverse=True)
        if not pool:
            replacement_level[position] = 0.0
            continue
        rank = max(_position_starter_demand(position, roster_positions) * num_teams, 1)
        replacement_level[position] = pool[rank - 1] if rank <= len(pool) else pool[-1]
    return replacement_level


def positional_strength_summary(
    roster: dict,
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    replacement_level: dict[str, float],
    roster_positions: list[str],
) -> pd.DataFrame:
    """Per-position value-over-replacement (VOR) for one roster.

    A value-based complement to `roster_needs_summary`'s young-core `need`
    flag: `need` is a rebuild-timeline question, `weak` (`vor <= 0`) is a
    trade-strategy one, against `position_replacement_levels`'s external
    baseline. Only the roster's own top-N players at a position (N =
    `_position_starter_demand()`) count toward `starter_value` — deep bench
    depth doesn't make a position "strong" if it never plays. See
    docs/rookie-draft-big-board.md's "Roster needs" section.
    """
    by_position: dict[str, list[float]] = {pos: [] for pos in FANTASY_POSITIONS}
    for player_id, info in roster_fantasy_players(roster, players):
        position = info.get("position")
        entry = fc_by_sleeper_id.get(player_id)
        adj_value = entry.get("adj_value") if entry else None
        by_position[position].append(adj_value if adj_value is not None else 0.0)

    rows = []
    for position in FANTASY_POSITIONS:
        values = sorted(by_position[position], reverse=True)
        starter_count = _position_starter_demand(position, roster_positions)
        starter_value = sum(values[:starter_count])
        rep_value = replacement_level.get(position, 0.0) * starter_count
        rows.append(
            {
                "pos": position,
                "starter_value": starter_value,
                "replacement_value": rep_value,
                "vor": starter_value - rep_value,
            }
        )
    summary = pd.DataFrame(rows).set_index("pos")
    summary["weak"] = summary["vor"] <= 0
    return summary.round(1)
