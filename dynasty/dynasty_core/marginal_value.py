"""Season-average marginal-lineup-value ranking, forced-drop recommendation, and free agents."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .constants import FLEX_ELIGIBLE_POSITIONS, NFL_WEEKS, SUPERFLEX_ELIGIBLE_POSITIONS
from .lineup import assign_starters, bye_for_row, player_value_rows, roster_total_capacity


def recommend_drop(
    player_ids: list[str],
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    league: dict,
    exclude_ids: frozenset[str] = frozenset(),
    ineligible_ids: frozenset[str] = frozenset(),
) -> dict[str, Any] | None:
    """Best player to drop: lowest-value bench player before any starter.

    `exclude_ids` can't be chosen but still compete for starting slots. `ineligible_ids`
    (taxi/IR) never start but can be dropped.
    """
    all_rows = player_value_rows(player_ids, players, fc_by_sleeper_id)
    eligible_rows = [r for r in all_rows if r["player_id"] not in ineligible_ids]
    assignments = assign_starters(eligible_rows, league["roster_positions"])
    starter_ids = {pid for _, pid in assignments if pid}

    rows = [r for r in all_rows if r["player_id"] not in exclude_ids]
    if not rows:
        return None

    bench_rows = [r for r in rows if r["player_id"] not in starter_ids]
    pool = bench_rows if bench_rows else rows
    worst = min(pool, key=lambda r: r["adj_value"] if r["adj_value"] is not None else -1)

    return {
        "player_id": worst["player_id"],
        "name": players.get(worst["player_id"], {}).get("full_name"),
        "pos": worst["pos"],
        "adj_value": worst["adj_value"],
        "is_starter": worst["player_id"] in starter_ids,
    }


def best_position_relevant_drop(
    candidate_id: str,
    hypothetical_ids: list[str],
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    byes: dict[str, int],
    league: dict,
    ineligible_ids: frozenset[str] = frozenset(),
) -> dict[str, Any] | None:
    """For one candidate, the drop among slot-sharing players that maximizes season value.

    Too costly for the ranking loop; meant for one on-demand lookup. With SUPER_FLEX,
    every position shares a slot, so this searches the whole roster.
    """
    candidate_position = players.get(candidate_id, {}).get("position")
    # Only expand for FLEX/SUPER_FLEX if the league actually has that slot.
    eligible_positions = {candidate_position}
    if "FLEX" in league["roster_positions"] and candidate_position in FLEX_ELIGIBLE_POSITIONS:
        eligible_positions |= FLEX_ELIGIBLE_POSITIONS
    if "SUPER_FLEX" in league["roster_positions"] and candidate_position in SUPERFLEX_ELIGIBLE_POSITIONS:
        eligible_positions |= SUPERFLEX_ELIGIBLE_POSITIONS

    rows = player_value_rows(hypothetical_ids, players, fc_by_sleeper_id)
    eligible_rows = [r for r in rows if r["player_id"] not in ineligible_ids]
    assignments = assign_starters(eligible_rows, league["roster_positions"])
    starter_ids = {pid for _, pid in assignments if pid}

    same_slot_ids = [pid for pid in hypothetical_ids if players.get(pid, {}).get("position") in eligible_positions]
    bench_pool = [pid for pid in same_slot_ids if pid not in starter_ids]
    drop_pool = bench_pool if bench_pool else same_slot_ids
    if not drop_pool:
        return None

    baseline = season_average_starter_value(hypothetical_ids, players, fc_by_sleeper_id, byes, league, ineligible_ids)

    best: dict[str, Any] | None = None
    for drop_id in drop_pool:
        roster_after = [pid for pid in hypothetical_ids if pid != drop_id] + [candidate_id]
        after = season_average_starter_value(roster_after, players, fc_by_sleeper_id, byes, league, ineligible_ids)
        marginal_value = after - baseline
        if best is None or marginal_value > best["marginal_value"]:
            info = players.get(drop_id, {})
            best = {
                "player_id": drop_id,
                "name": info.get("full_name"),
                "pos": info.get("position"),
                "is_starter": drop_id in starter_ids,
                "marginal_value": marginal_value,
            }
    return best


def season_average_starter_value(
    player_ids: list[str],
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    byes: dict[str, int],
    league: dict,
    ineligible_ids: frozenset[str] = frozenset(),
) -> float:
    """Optimal lineup value averaged over 18 weeks, skipping bye'd players. Taxi/IR never start."""
    rows = player_value_rows(player_ids, players, fc_by_sleeper_id)
    eligible_rows = [r for r in rows if r["player_id"] not in ineligible_ids]

    bye_by_player = {r["player_id"]: bye_for_row(r, players, byes) for r in eligible_rows}

    total = 0.0
    for week in NFL_WEEKS:
        week_rows = [r for r in eligible_rows if bye_by_player[r["player_id"]] != week]
        value_by_id = {r["player_id"]: r["adj_value"] or 0 for r in week_rows}
        assignments = assign_starters(week_rows, league["roster_positions"])
        total += sum(value_by_id.get(pid, 0) for _, pid in assignments if pid)

    return total / len(NFL_WEEKS)


def rank_by_marginal_value(
    candidate_ids: list[str],
    hypothetical_ids: list[str],
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    byes: dict[str, int],
    league: dict,
    top_n: int = 3,
    exclude_from_drop: frozenset[str] = frozenset(),
    ineligible_ids: frozenset[str] = frozenset(),
    reserve_filled: int = 0,
    taxi_eligible: bool = True,
    taxi_filled: int = 0,
) -> list[dict]:
    """Rank candidates by how much they raise season-average lineup value.

    Each candidate is added, with a `recommend_drop()` forced only at capacity.
    `exclude_from_drop` protects players from the drop; `taxi_eligible`/`taxi_filled`
    pass through to `roster_total_capacity`. Returns up to `top_n`
    `{player_id, marginal_value, drop}`, best first.
    """
    if not candidate_ids:
        return []

    total_capacity = roster_total_capacity(league, reserve_filled, taxi_eligible, taxi_filled)
    baseline = season_average_starter_value(hypothetical_ids, players, fc_by_sleeper_id, byes, league, ineligible_ids)

    results = []
    for candidate_id in candidate_ids:
        with_candidate = hypothetical_ids + [candidate_id]
        if len(with_candidate) > total_capacity:
            drop = recommend_drop(
                with_candidate,
                players,
                fc_by_sleeper_id,
                league,
                exclude_ids=exclude_from_drop,
                ineligible_ids=ineligible_ids,
            )
        else:
            drop = None
        roster_after = [pid for pid in with_candidate if drop is None or pid != drop["player_id"]]
        after = season_average_starter_value(roster_after, players, fc_by_sleeper_id, byes, league, ineligible_ids)
        results.append({"player_id": candidate_id, "marginal_value": after - baseline, "drop": drop})

    results.sort(key=lambda r: r["marginal_value"], reverse=True)
    return results[:top_n]


def free_agent_board(
    pool: dict[str, dict],
    roster: dict,
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    byes: dict[str, int],
    league: dict,
    top_n: int = 25,
) -> pd.DataFrame:
    """Free agents ranked by marginal lineup value for this roster, positive values only.

    Adds can't use an open taxi slot (`taxi_eligible=False`). Values are rounded before
    the `> 0` filter so the display never shows "+0.0".
    """
    ineligible_ids = frozenset(roster.get("taxi") or []) | frozenset(roster.get("reserve") or [])
    reserve_filled = len(roster.get("reserve") or [])
    taxi_filled = len(roster.get("taxi") or [])
    ranked = rank_by_marginal_value(
        list(pool.keys()),
        list(roster.get("players") or []),
        players,
        fc_by_sleeper_id,
        byes,
        league,
        top_n=top_n,
        ineligible_ids=ineligible_ids,
        reserve_filled=reserve_filled,
        taxi_eligible=False,
        taxi_filled=taxi_filled,
    )

    rows = []
    for candidate in ranked:
        marginal_value = round(candidate["marginal_value"], 1)
        if marginal_value <= 0:
            continue
        info = players.get(candidate["player_id"], {})
        drop = candidate["drop"]
        rows.append(
            {
                # Join key for callers (FAAB guidance); drop before rendering.
                "player_id": candidate["player_id"],
                "name": info.get("full_name"),
                "pos": info.get("position"),
                "team": info.get("team"),
                "marginal_value": marginal_value,
                "drop_name": drop["name"] if drop else None,
                "drop_is_starter": drop["is_starter"] if drop else None,
            }
        )
    return pd.DataFrame(rows)
