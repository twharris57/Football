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
    """Dot product of a player's projected stat categories against this league's real scoring settings.

    Not `player_scoring._stat_points` - that translates `nfl_data_py`'s
    differently-named historical columns. Here both sides already speak
    Sleeper's own stat-key vocabulary (`rec`, `rec_yd`, `rush_td`, `rush_fd`,
    `rec_fd`, `rush_40p`, `rec_40p`, `pass_cmp_40p`, ... confirmed live to
    line up 1:1), so no crosswalk is needed. `bonus_rec_te` was assumed to be
    an exception - a position-conditional *weight* a global, non-league-scoped
    endpoint could "never" emit as its own raw-stat key - but a live payload
    check (`VA-7`, 2026-08-28) found Sleeper's projections do emit it
    directly, scoped correctly to TEs, holding the TE's own reception count.
    The dot product above already prices it in correctly whenever present;
    the fallback below only fires when a TE projection omits the key
    (observed rarely, near-zero-reception TEs), so a normal TE is never
    double-counted.

    Confirmed absent from every payload checked (`VA-7`): `pass_td_40p`,
    `pass_td_50p`, `rush_td_40p`, `rush_td_50p`, `rec_td_40p`, `rec_td_50p` -
    real, scored categories for this league that Sleeper's projections simply
    don't carry (no per-play length data behind a weekly projection), so
    weekly lineup projections systematically miss these bonuses with no
    fallback able to recover them - see docs/rookie-draft-big-board.md's
    "Known limitations".

    Non-numeric stat values are skipped rather than trusted blindly - an
    undocumented endpoint can plausibly return `None` for a rarely-projected
    category, and this pipeline degrades gracefully everywhere else rather
    than crashing on an external-data surprise.
    """
    points = sum(
        value * scoring_settings.get(stat, 0.0)
        for stat, value in projection.items()
        if isinstance(value, (int, float))
    )
    if position == "TE" and "bonus_rec_te" not in projection:
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
    """Build {player_id, pos, adj_value} rows from this week's projected points - same
    shape as `player_value_rows()`, so both can feed `assign_starters()` unchanged, but
    `adj_value` here is a this-week points projection, not dynasty trade value. A player
    with no projection entry gets `adj_value=None`, the same missing-data handling
    `player_value_rows()` already uses for an unresolved market value.
    """
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


def _lineup_breakdown_from_rows(
    rows: list[dict], roster: dict, players: dict[str, dict], roster_positions: list[str]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Shared assignment/grouping logic behind `lineup_breakdown()`/`weekly_lineup_breakdown()`.

    The two only differ in how each row's `adj_value` gets computed
    (dynasty trade value vs. this week's projected points, via
    `player_value_rows()`/`weekly_projected_value_rows()`) — starter
    assignment and the taxi/reserve/bench split are the same question
    either way, so that logic lives here once rather than twice.
    """
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
    """Return (starters, bench, taxi, ir) for the roster's optimal lineup by dynasty value.

    A long-run asset-value ranking, not week- or injury-aware by design —
    this is what trade/drop/draft-plan decisions correctly key off of (see
    `valuation_principles.md`'s "one valuation strategy" rule), so it stays
    untouched. See `weekly_lineup_breakdown()` for the this-week-projected
    alternative. Taxi and IR/reserve players are in `roster["players"]`
    alongside the real bench, so they're split out via
    `roster["taxi"]`/`roster["reserve"]` (plain player_id lists) and
    excluded from the starter assignment itself — Sleeper doesn't allow
    starting them.
    """
    rows = player_value_rows(roster.get("players") or [], players, fc_by_sleeper_id)
    return _lineup_breakdown_from_rows(rows, roster, players, league["roster_positions"])


def weekly_lineup_breakdown(
    roster: dict, players: dict[str, dict], projections: dict[str, dict], league: dict
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (starters, bench, taxi, ir) for the roster's optimal lineup by THIS WEEK's
    projected points — a genuinely different ranking question than `lineup_breakdown()`'s
    dynasty value (who wins the most points this week vs. long-run asset value), reusing
    `assign_starters()`/the same taxi-reserve-bench split unchanged rather than a second,
    parallel implementation of "who starts." An empty `projections` dict (a failed fetch —
    see `state.py`) makes every row's `adj_value` `None`, same as an unresolved market
    value — `assign_starters()` already handles that (treats `None` as lowest priority),
    so this degrades to an arbitrary-order lineup rather than crashing.
    """
    rows = weekly_projected_value_rows(roster.get("players") or [], players, projections, league["scoring_settings"])
    return _lineup_breakdown_from_rows(rows, roster, players, league["roster_positions"])


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
    (see `.claude/PROJECT_PLAN_DYNASTY.md`'s `RT-8`) and most veteran free agents
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
