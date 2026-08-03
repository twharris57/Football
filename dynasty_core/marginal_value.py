"""Season-average marginal-lineup-value ranking, forced-drop recommendation, and free agents."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .constants import FLEX_ELIGIBLE_POSITIONS, NFL_WEEKS, SUPERFLEX_ELIGIBLE_POSITIONS
from .lineup import assign_starters, player_value_rows, roster_total_capacity


def recommend_drop(
    player_ids: list[str],
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    league: dict,
    exclude_ids: frozenset[str] = frozenset(),
    ineligible_ids: frozenset[str] = frozenset(),
) -> dict[str, Any] | None:
    """Recommend the single best player to drop: lowest-value bench player, over starters.

    `exclude_ids` protects specific players (e.g. just picked earlier in the
    same multi-round plan, or a trade's own incoming players) from being
    *chosen* as the drop - it does not remove them from the starter
    assignment itself. An excluded player still legitimately occupies a
    real slot and can still push someone else down to bench; computing
    `assign_starters()` on a `rows` list that already excluded them would
    understate real competition for slots and let a droppable player who'd
    actually be bench read as `is_starter: True` (see
    `.claude/conventions/valuation_principles.md`'s "Exclusion filters
    change the outcome for everyone else" rule). `ineligible_ids` (taxi/IR
    players) are never eligible to be assigned a starting slot here -
    Sleeper doesn't allow it - so they can't be wrongly protected from the
    drop pool as a false "starter"; they still land in `rows` and so can
    still be recommended for drop themselves.
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
    """For one specific candidate, search which drop actually maximizes marginal value.

    `recommend_drop()` (used by the main per-round ranking, for
    performance) is a cheap heuristic — lowest-value bench player, full
    stop — that can suggest the same drop for very different candidates.
    This instead restricts the search to players who share a slot type
    with the candidate (own position, plus FLEX/SUPER_FLEX-eligible
    positions if the candidate qualifies), tries dropping each, and
    returns whichever resulting roster has the highest season-average
    starting value. Deliberately not used inside `rank_by_marginal_value`'s
    per-round loop — evaluating every drop option for every candidate would
    multiply that pass's cost by the search pool size. Meant for on-demand
    lookup (one candidate at a time, e.g. a UI dropdown selection).
    """
    candidate_position = players.get(candidate_id, {}).get("position")
    # Gated on whether the league's actual roster_positions has that slot
    # type at all - same condition assign_starters itself uses - not just
    # on FLEX_ELIGIBLE_POSITIONS/SUPERFLEX_ELIGIBLE_POSITIONS membership,
    # so a league without a FLEX or SUPER_FLEX slot doesn't get a
    # meaningless expansion for a position that could never actually share
    # a real slot with the candidate.
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
    """Average optimal starting-lineup value across all 18 weeks, excluding bye'd players each week.

    The season-long analog of `lineup_breakdown`'s single snapshot: every
    player misses exactly one week (their own bye), so this captures the
    *interaction* of a bye with positional depth, not a blanket bye
    penalty. `ineligible_ids` (taxi/IR players) never win a starting slot
    here, matching Sleeper's own rule. See docs/rookie-draft-big-board.md's
    "Ranking" section for the full rationale.
    """
    rows = player_value_rows(player_ids, players, fc_by_sleeper_id)
    eligible_rows = [r for r in rows if r["player_id"] not in ineligible_ids]
    bye_by_player = {r["player_id"]: byes.get(players.get(r["player_id"], {}).get("team")) for r in eligible_rows}

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
    """Rank candidates by season-average marginal starting-lineup value, not raw trade value.

    For each candidate: simulate adding them (only forcing the resulting
    `recommend_drop()` if the roster is already at total capacity — see
    `roster_total_capacity`), and measure the delta to
    `season_average_starter_value`. `exclude_from_drop` protects specific
    players (e.g. picked in an earlier round of the same multi-round plan)
    from being recommended for drop; `ineligible_ids` (current taxi/IR
    players) are never assignable to a starting slot in the simulation.
    `taxi_eligible`/`taxi_filled` pass straight through to
    `roster_total_capacity` — `taxi_eligible=True` (default) for the rookie
    draft plan, `False` (with `taxi_filled` set to the roster's actual taxi
    headcount) for `free_agent_board`'s veteran candidates. Returns up to
    `top_n` entries (player_id, marginal_value, drop), sorted best first —
    the first is the recommended pick, the rest are backup alternates. Full
    rationale in docs/rookie-draft-big-board.md's "Ranking" section.
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
    """Rank available free agents by season-average marginal starting-lineup value against this roster.

    Reuses `rank_by_marginal_value` exactly like the draft plan does - not a
    second valuation model (see `.claude/conventions/valuation_principles.md`).
    Passes `taxi_eligible=False`: Sleeper's real accrued-experience taxi rule
    isn't modeled here, so a candidate is only ever added to an open active
    roster slot or via a drop, never assumed to fit an open taxi slot the
    way a rookie safely can - a documented gap (`.claude/PROJECT_PLAN.md`),
    not a silent one. Also passes `taxi_filled` (this roster's actual current
    taxi headcount) so an existing taxi stash - the norm for a rebuilding
    roster in this league - isn't misread as already over capacity before
    any candidate is even considered; only a *new* candidate is barred from
    an open taxi slot, existing occupants still count toward the ceiling
    the same way occupied reserve slots already do. `pool` is typically
    `free_agent_pool()`'s output; accepting it as a plain parameter (rather
    than recomputing it here) lets `gather_state` compute it once per
    refresh, not once per team looked up through the Roster tab's team
    selector.

    Evaluates every candidate in `pool` (candidates × 18 `assign_starters`
    calls, no per-round multiplication like the draft plan's ~20,000-call
    pass has) before sorting and slicing to `top_n` - cheap enough even at
    free-agent-pool scale (~350-450 players) to score everyone rather than
    pre-filtering.
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
        info = players.get(candidate["player_id"], {})
        drop = candidate["drop"]
        rows.append(
            {
                "name": info.get("full_name"),
                "pos": info.get("position"),
                "team": info.get("team"),
                "marginal_value": round(candidate["marginal_value"], 1),
                "drop_name": drop["name"] if drop else None,
                "drop_is_starter": drop["is_starter"] if drop else None,
            }
        )
    return pd.DataFrame(rows)
