"""Starting-lineup slot assignment and roster capacity math."""

from __future__ import annotations

import pandas as pd

from .constants import (
    FANTASY_POSITIONS,
    FLEX_ELIGIBLE_POSITIONS,
    SUPERFLEX_ELIGIBLE_POSITIONS,
)


def player_value_rows(player_ids: list[str], players: dict[str, dict], fc_by_sleeper_id: dict[str, dict]) -> list[dict]:
    """Build {player_id, pos, adj_value} rows for the given players, for lineup/drop logic."""
    rows = []
    for player_id in player_ids:
        info = players.get(player_id, {})
        position = info.get("position")
        if position not in FANTASY_POSITIONS:
            continue
        fc_entry = fc_by_sleeper_id.get(player_id)
        rows.append({"player_id": player_id, "pos": position, "adj_value": fc_entry.get("adj_value") if fc_entry else None})
    return rows


def _weekly_projected_points(projection: dict[str, float], scoring_settings: dict[str, float], position: str) -> float:
    """Projected points: each numeric projected stat × its `scoring_settings` weight.

    Sleeper's projection keys match `scoring_settings`, including `bonus_rec_te`; the TE
    fallback only applies when that key isn't usable. Long-TD bonuses (`*_td_40p`/`50p`)
    aren't projected, so they're always missing.
    """
    points = sum(
        value * scoring_settings.get(stat, 0.0)
        for stat, value in projection.items()
        if isinstance(value, (int, float))
    )
    if position == "TE" and not isinstance(projection.get("bonus_rec_te"), (int, float)):
        receptions = projection.get("rec")
        if isinstance(receptions, (int, float)):
            points += receptions * scoring_settings.get("bonus_rec_te", 0.0)
    return points


def weekly_projected_value_rows(
    player_ids: list[str],
    players: dict[str, dict],
    projections: dict[str, dict],
    scoring_settings: dict[str, float],
) -> list[dict]:
    """Like `player_value_rows()`, but `adj_value` is this week's projected points (`None` if unprojected)."""
    rows = []
    for player_id in player_ids:
        info = players.get(player_id, {})
        position = info.get("position")
        if position not in FANTASY_POSITIONS:
            continue
        projection = projections.get(player_id)
        adj_value = _weekly_projected_points(projection, scoring_settings, position) if projection else None
        rows.append({"player_id": player_id, "pos": position, "adj_value": adj_value})
    return rows


def bye_for_row(row: dict, players: dict[str, dict], byes: dict[str, int]) -> int | None:
    """Resolve a `player_value_rows()` row's bye week via its player's current NFL team."""
    team = players.get(row["player_id"], {}).get("team")
    return byes.get(team) if team else None


def assign_starters(player_rows: list[dict], roster_positions: list[str]) -> list[tuple[str, str | None]]:
    """Fill starting slots most-restrictive first: QB/RB/WR/TE, then FLEX, then SUPER_FLEX.

    Optimal for nested slot eligibility. Returns `(slot, player_id)` per starting slot,
    with `None` when no eligible player remains.
    """
    remaining = sorted(
        (r for r in player_rows if r["pos"] in FANTASY_POSITIONS),
        key=lambda r: r["adj_value"] if r["adj_value"] is not None else -1,
        reverse=True,
    )

    def take_best(eligible: frozenset[str]) -> str | None:
        for i, row in enumerate(remaining):
            if row["pos"] in eligible:
                return remaining.pop(i)["player_id"]
        return None

    assignments: list[tuple[str, str | None]] = []
    for pos in ("QB", "RB", "WR", "TE"):
        for _ in range(roster_positions.count(pos)):
            assignments.append((pos, take_best(frozenset({pos}))))
    for _ in range(roster_positions.count("FLEX")):
        assignments.append(("FLEX", take_best(FLEX_ELIGIBLE_POSITIONS)))
    for _ in range(roster_positions.count("SUPER_FLEX")):
        assignments.append(("SUPER_FLEX", take_best(SUPERFLEX_ELIGIBLE_POSITIONS)))
    return assignments


def _lineup_breakdown_from_rows(
    rows: list[dict], roster: dict, players: dict[str, dict], roster_positions: list[str]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Starter assignment and taxi/IR/bench split shared by both lineup views."""
    taxi_ids = set(roster.get("taxi") or [])
    reserve_ids = set(roster.get("reserve") or [])
    value_by_id = {r["player_id"]: r["adj_value"] for r in rows}
    active_rows = [r for r in rows if r["player_id"] not in taxi_ids and r["player_id"] not in reserve_ids]
    assignments = assign_starters(active_rows, roster_positions)
    starter_ids = {pid for _, pid in assignments if pid}

    starter_rows = []
    for slot, pid in assignments:
        if pid is None:
            starter_rows.append({"slot": slot, "name": "(empty)", "pos": None, "adj_value": None})
            continue
        info = players.get(pid, {})
        starter_rows.append(
            {"slot": slot, "name": info.get("full_name"), "pos": info.get("position"), "adj_value": value_by_id[pid]}
        )

    def group_df(predicate) -> pd.DataFrame:
        rows_for_group = [
            {"name": players.get(r["player_id"], {}).get("full_name"), "pos": r["pos"], "adj_value": r["adj_value"]}
            for r in rows
            if predicate(r["player_id"])
        ]
        group_df_ = pd.DataFrame(rows_for_group)
        if not group_df_.empty:
            group_df_ = group_df_.sort_values("adj_value", ascending=False, na_position="last").reset_index(drop=True)
        return group_df_

    bench_df = group_df(lambda pid: pid not in starter_ids and pid not in taxi_ids and pid not in reserve_ids)
    taxi_df = group_df(lambda pid: pid in taxi_ids)
    reserve_df = group_df(lambda pid: pid in reserve_ids)

    return pd.DataFrame(starter_rows), bench_df, taxi_df, reserve_df


def lineup_breakdown(
    roster: dict, players: dict[str, dict], fc_by_sleeper_id: dict[str, dict], league: dict
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """`(starters, bench, taxi, ir)` by dynasty value. Taxi/IR never start."""
    rows = player_value_rows(roster.get("players") or [], players, fc_by_sleeper_id)
    return _lineup_breakdown_from_rows(rows, roster, players, league["roster_positions"])


def weekly_lineup_breakdown(
    roster: dict, players: dict[str, dict], projections: dict[str, dict], league: dict
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """`(starters, bench, taxi, ir)` by this week's projections. No projections → arbitrary order."""
    rows = weekly_projected_value_rows(roster.get("players") or [], players, projections, league["scoring_settings"])
    return _lineup_breakdown_from_rows(rows, roster, players, league["roster_positions"])


def roster_capacity(roster: dict, league: dict) -> dict[str, int]:
    """Active, taxi, and IR slot usage. IR players are excluded from `active_filled`."""
    all_player_ids = roster.get("players") or []
    taxi_ids = roster.get("taxi") or []
    reserve_ids = roster.get("reserve") or []

    active_total = len(league["roster_positions"])
    active_filled = len(all_player_ids) - len(taxi_ids) - len(reserve_ids)
    taxi_total = league["settings"].get("taxi_slots", 0)
    taxi_filled = len(taxi_ids)
    reserve_total = league["settings"].get("reserve_slots", 0)
    reserve_filled = len(reserve_ids)

    return {
        "active_total": active_total,
        "active_filled": active_filled,
        "active_open": active_total - active_filled,
        "taxi_total": taxi_total,
        "taxi_filled": taxi_filled,
        "taxi_open": taxi_total - taxi_filled,
        "reserve_total": reserve_total,
        "reserve_filled": reserve_filled,
        "reserve_open": reserve_total - reserve_filled,
    }


def roster_total_capacity(
    league: dict, reserve_filled: int = 0, taxi_eligible: bool = True, taxi_filled: int = 0
) -> int:
    """Total roster ceiling: active + taxi + *occupied* IR slots.

    Empty IR slots don't count — a new player can't be placed there. With
    `taxi_eligible=False` (veterans), open taxi slots don't count but filled ones do.
    """
    taxi_slots = league["settings"].get("taxi_slots", 0) if taxi_eligible else taxi_filled
    return len(league["roster_positions"]) + taxi_slots + reserve_filled
