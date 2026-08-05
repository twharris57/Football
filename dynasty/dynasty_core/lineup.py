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


def assign_starters(player_rows: list[dict], roster_positions: list[str]) -> list[tuple[str, str | None]]:
    """Assign players to starting slots, most-restrictive slot first (QB/RB/WR/TE,
    then FLEX, then SUPER_FLEX).

    Provably optimal for this league's nested slot eligibility — QB's
    dedicated slot ⊂ SUPER_FLEX's eligible set, RB/WR/TE dedicated ⊂
    FLEX's ⊂ SUPER_FLEX's — via a standard greedy exchange argument, not
    just a heuristic. See docs/rookie-draft-big-board.md's "Ranking"
    section for the full proof sketch. Returns one (slot_label, player_id)
    pair per starting slot in `roster_positions` (excluding bench);
    player_id is None if no eligible player remains for that slot.
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


def lineup_breakdown(
    roster: dict, players: dict[str, dict], fc_by_sleeper_id: dict[str, dict], league: dict
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (starters, bench, taxi, ir) for the roster's optimal lineup by current value.

    A snapshot, not week- or injury-aware (a planned refinement). Taxi and
    IR/reserve players are in `roster["players"]` alongside the real bench,
    so they're split out via `roster["taxi"]`/`roster["reserve"]` (plain
    player_id lists) and excluded from the starter assignment itself —
    Sleeper doesn't allow starting them.
    """
    taxi_ids = set(roster.get("taxi") or [])
    reserve_ids = set(roster.get("reserve") or [])
    rows = player_value_rows(roster.get("players") or [], players, fc_by_sleeper_id)
    value_by_id = {r["player_id"]: r["adj_value"] for r in rows}
    active_rows = [r for r in rows if r["player_id"] not in taxi_ids and r["player_id"] not in reserve_ids]
    assignments = assign_starters(active_rows, league["roster_positions"])
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


def roster_capacity(roster: dict, league: dict) -> dict[str, int]:
    """Return active-roster, taxi-squad, and IR/reserve slot usage for the given roster.

    `roster["reserve"]` (a plain player_id list, same shape as `roster["taxi"]`)
    is reliably derivable after all — confirmed directly against the live
    league, including rosters with IR players populated — so it's counted
    here and excluded from `active_filled`, same as taxi.
    """
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
    """Return the combined active-roster + taxi-squad + occupied-reserve slot count.

    Used to decide whether adding a player genuinely requires a drop, for
    simulated/hypothetical rosters — those are a flat player-id list (see
    `multi_round_plan`) with no active/taxi/reserve split, so this is the
    "is there room *anywhere*" signal. `reserve_filled` (the roster's
    actual current IR headcount, passed by the caller — not the league's
    full `reserve_slots` setting) accounts only for *existing* IR occupants:
    a newly-drafted rookie can never land on reserve (that requires a real
    injury designation), so an empty IR slot must not read as room for one.

    `taxi_eligible` gates whether a *new* candidate could occupy an *open*
    taxi slot — `True` (default) for rookies, always taxi-eligible in this
    draft; `False` for `free_agent_board`/`evaluate_trade`'s candidates,
    since Sleeper's real accrued-experience taxi rule isn't modeled here
    (see `.claude/PROJECT_PLAN.md`'s `RT-8`) and most veteran free agents
    or trade targets wouldn't actually qualify. When `taxi_eligible=False`,
    the ceiling still credits `taxi_filled` (the roster's actual current
    taxi headcount, same shape as `reserve_filled`) rather than dropping
    taxi capacity to zero outright — existing taxi occupants are already
    counted in the player-id list this ceiling is compared against
    (`lineup_breakdown`: "Taxi and IR/reserve players are in
    `roster["players"]` alongside the real bench"), so zeroing taxi
    capacity entirely would make a normal existing taxi stash look like it
    was already over capacity before anything changed.
    """
    taxi_slots = league["settings"].get("taxi_slots", 0) if taxi_eligible else taxi_filled
    return len(league["roster_positions"]) + taxi_slots + reserve_filled
