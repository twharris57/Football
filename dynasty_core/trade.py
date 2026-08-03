"""Sellable-depth surfacing, two-sided trade evaluation, and the trade-target optimizer."""

from __future__ import annotations

import itertools
from typing import Any

import pandas as pd

from .byes import gap_delta
from .constants import FANTASY_POSITIONS, FLEX_ELIGIBLE_POSITIONS
from .lineup import roster_total_capacity
from .marginal_value import recommend_drop, season_average_starter_value
from .player_pools import roster_fantasy_players
from .roster_needs import (
    _position_starter_demand,
    need_positions,
    positional_strength_summary,
    roster_needs_summary,
)

# Trade-target optimizer (RT-12) bounds - judgment calls, not derived from
# any league rule, same status as the rebuild-strategy constants elsewhere.
# Sized for this league's realistic team count (~12) and per-team
# sellable-pool size (typically 5-15 candidates between bench depth and
# owned picks) - bounds the combinatorial search before the expensive
# evaluate_trade() calls.
TRADE_OFFER_POOL_CAP = 12
TRADE_OFFER_MAX_COMBO_SIZE = 3
TRADE_OFFER_PREFILTER_LOW = 0.5
TRADE_OFFER_PREFILTER_HIGH = 2.0
TRADE_OFFER_PARTNER_TOLERANCE_PCT = 0.15
TRADE_OFFER_MIN_ABSOLUTE_TOLERANCE = 25.0


def sellable_players(
    roster: dict,
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    replacement_level: dict[str, float],
    league: dict,
    byes: dict[str, int],
) -> pd.DataFrame:
    """Rostered bench depth worth shopping for trade value, not just cutting for nothing.

    A position qualifies if its own starters clear replacement level
    (`positional_strength_summary`'s `vor > 0`); within a qualifying
    position, "sellable" is the roster's depth beyond what's needed to
    start there — reserving this roster's `FLEX` slot count against every
    FLEX-eligible position too, unlike `starter_value`'s dedicated-slot-only
    count, so a real weekly FLEX starter isn't misflagged as surplus. A
    candidate must also survive `gap_delta` (dropping them can't open a
    weekly-depth hole), and rookies are excluded (dynasty upside to hold,
    not surplus to sell). Deliberately excludes actual starters — that's a
    bigger strategic call, left for a human to judge against a specific
    offer. Returns a candidate list sorted by `adj_value`, not a
    recommendation. Includes `player_id` (an internal join key for callers
    like `find_trade_offers()` that need to act on a candidate, not just
    display it - drop it before rendering a table). Full rationale in
    docs/rookie-draft-big-board.md's "Trade targets & sells" section.
    """
    roster_positions = league["roster_positions"]
    strength = positional_strength_summary(roster, players, fc_by_sleeper_id, replacement_level, roster_positions)
    vor_by_position = strength["vor"].to_dict()
    roster_player_ids = roster.get("players") or []
    flex_slots = roster_positions.count("FLEX")

    by_position: dict[str, list[tuple[str, dict, float]]] = {pos: [] for pos in FANTASY_POSITIONS}
    for player_id, info in roster_fantasy_players(roster, players):
        fc_entry = fc_by_sleeper_id.get(player_id)
        adj_value = fc_entry.get("adj_value") if fc_entry else None
        by_position[info["position"]].append((player_id, info, adj_value if adj_value is not None else 0.0))

    rows = []
    for position, entries in by_position.items():
        if vor_by_position[position] <= 0:
            continue
        starter_count = _position_starter_demand(position, roster_positions)
        if position in FLEX_ELIGIBLE_POSITIONS:
            starter_count += flex_slots
        depth = sorted(entries, key=lambda e: e[2], reverse=True)[starter_count:]
        for player_id, info, _sort_value in depth:
            if not info.get("years_exp"):
                continue
            after_roster = {**roster, "players": [pid for pid in roster_player_ids if pid != player_id]}
            if not gap_delta(roster, after_roster, players, byes, league).empty:
                continue
            fc_entry = fc_by_sleeper_id.get(player_id)
            rows.append(
                {
                    "player_id": player_id,
                    "name": info.get("full_name"),
                    "pos": position,
                    "age": info.get("age"),
                    "value": fc_entry.get("value") if fc_entry else None,
                    "adj_value": fc_entry.get("adj_value") if fc_entry else None,
                    "position_vor": vor_by_position[position],
                }
            )
    sellable = pd.DataFrame(rows)
    if sellable.empty:
        return sellable
    return sellable.sort_values("adj_value", ascending=False, na_position="last").reset_index(drop=True)


def evaluate_trade(
    roster: dict,
    outgoing_player_ids: list[str],
    incoming_player_ids: list[str],
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    byes: dict[str, int],
    league: dict,
    outgoing_pick_value: float = 0.0,
    incoming_pick_value: float = 0.0,
) -> dict[str, Any]:
    """Evaluate one side of a proposed multi-asset trade (players + picks) for one roster.

    Two independent reads: `lineup_delta` (`season_average_starter_value()`
    before vs. after) and `asset_value_delta` (`adj_value` summed each
    side, plus caller-supplied pick values) — a trade can be lineup-critical
    but value-negative, or the reverse. Evaluating the other side of the
    same trade is this function called again with the partner's roster and
    the two asset lists swapped, not a second code path.

    `over_capacity` uses `taxi_eligible=False` (a traded-for player is
    assumed to be an established veteran, not taxi-safe like a rookie), and
    `reserve_filled`/`taxi_filled` are computed *post*-trade (excluding any
    outgoing player already on IR/taxi, since trading them away genuinely
    frees that slot). When `roster_after` exceeds capacity, `recommend_drop()`
    is applied once per player over the limit; `recommended_drops` is that
    list, and `lineup_delta_after_drops` is the trade's real net lineup
    impact including those forced cuts, while `lineup_delta` stays the
    trade-only number. Newly-incoming players are protected from being
    recommended for their own trade's forced cut via `exclude_ids`.
    """
    current_ids = list(roster.get("players") or [])
    outgoing_set = set(outgoing_player_ids)
    roster_after = [pid for pid in current_ids if pid not in outgoing_set] + list(incoming_player_ids)
    ineligible_ids = frozenset(roster.get("taxi") or []) | frozenset(roster.get("reserve") or [])

    before_value = season_average_starter_value(current_ids, players, fc_by_sleeper_id, byes, league, ineligible_ids)
    after_value = season_average_starter_value(roster_after, players, fc_by_sleeper_id, byes, league, ineligible_ids)

    def _adj_value_sum(player_ids: list[str]) -> float:
        total = 0.0
        for player_id in player_ids:
            entry = fc_by_sleeper_id.get(player_id)
            total += (entry.get("adj_value") or 0.0) if entry else 0.0
        return total

    outgoing_value = _adj_value_sum(outgoing_player_ids) + outgoing_pick_value
    incoming_value = _adj_value_sum(incoming_player_ids) + incoming_pick_value

    reserve_filled = len((frozenset(roster.get("reserve") or [])) - outgoing_set)
    taxi_filled = len((frozenset(roster.get("taxi") or [])) - outgoing_set)
    capacity = roster_total_capacity(league, reserve_filled, taxi_eligible=False, taxi_filled=taxi_filled)

    overflow = max(0, len(roster_after) - capacity)
    recommended_drops: list[dict[str, Any]] = []
    roster_after_drops = list(roster_after)
    incoming_set = frozenset(incoming_player_ids)
    for _ in range(overflow):
        drop = recommend_drop(
            roster_after_drops, players, fc_by_sleeper_id, league, exclude_ids=incoming_set, ineligible_ids=ineligible_ids
        )
        if drop is None:
            break
        recommended_drops.append(drop)
        roster_after_drops = [pid for pid in roster_after_drops if pid != drop["player_id"]]

    after_value_post_drops = (
        season_average_starter_value(roster_after_drops, players, fc_by_sleeper_id, byes, league, ineligible_ids)
        if recommended_drops
        else after_value
    )

    return {
        "lineup_delta": after_value - before_value,
        "lineup_delta_after_drops": after_value_post_drops - before_value,
        "asset_value_delta": incoming_value - outgoing_value,
        "over_capacity": overflow > 0,
        "roster_size_after": len(roster_after),
        "capacity": capacity,
        "recommended_drops": recommended_drops,
    }


def find_trade_offers(
    your_roster: dict,
    partner_roster: dict,
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    byes: dict[str, int],
    league: dict,
    replacement_level: dict[str, float],
    pick_value_table: pd.DataFrame,
    target_player_id: str | None = None,
    target_pick_name: str | None = None,
    top_n: int = 3,
) -> dict[str, Any]:
    """Given one asset on partner_roster, decide whether it's worth pursuing and search for a mutually-beneficial offer.

    Exactly one of target_player_id/target_pick_name must be given - a
    single asset, not a bundle (`evaluate_trade()` already handles an
    already-specified multi-asset trade). Composes `evaluate_trade()`, no
    new valuation model (see .claude/conventions/valuation_principles.md).

    `target_read`: `evaluate_trade()` with zero outgoing - the marginal
    lineup value of acquiring the target for free, plus its market value
    for context.

    `target_value_resolved` is `False` when the target has no real market
    value (an unranked player, or an unmatched pick name) - the offer
    search doesn't run in that case (`offers`/`combos_*` come back empty)
    rather than searching against a fabricated `$0` baseline. Resolved via
    `pd.notna()`, not a bare `value or 0.0`, since `NaN` is truthy in
    Python and would otherwise defeat every downstream comparison (see
    valuation_principles.md's NaN rule).

    `offers`: every combination (size 1..`TRADE_OFFER_MAX_COMBO_SIZE`) of
    your own `sellable_players()`/pick pool, first pruned to drop any
    candidate priced beyond `TRADE_OFFER_PREFILTER_HIGH` of the target's
    value (no combo containing one could ever land in-band), then capped
    to `TRADE_OFFER_POOL_CAP` by value, pre-filtered to a value band around
    the target, and verified two-sided via `evaluate_trade()`. A combo
    survives only if the partner's own `asset_value_delta` stays within
    `TRADE_OFFER_PARTNER_TOLERANCE_PCT` of zero - the one hard acceptance
    gate. Combos touching one of the partner's current `need_positions`
    (today's roster, not post-trade) rank ahead of otherwise-equal
    alternatives, as a tiebreaker only. Ranked best-for-you first, then
    need-match, then fewest assets. Returns up to `top_n`, empty if
    nothing clears the bar.

    `combos_considered`/`combos_evaluated` are the raw and post-prefilter
    combo counts, so an empty result can say something concrete.
    """
    if bool(target_player_id) == bool(target_pick_name):
        raise ValueError("Exactly one of target_player_id or target_pick_name must be given.")

    pick_value_by_name = dict(zip(pick_value_table["pick"], pick_value_table["value"]))

    if target_player_id:
        target_entry = fc_by_sleeper_id.get(target_player_id)
        raw_target_value = target_entry.get("adj_value") if target_entry else None
        target_read = evaluate_trade(your_roster, [], [target_player_id], players, fc_by_sleeper_id, byes, league)
    else:
        raw_target_value = pick_value_by_name.get(target_pick_name)
        target_read = evaluate_trade(
            your_roster, [], [], players, fc_by_sleeper_id, byes, league,
            incoming_pick_value=(
                float(raw_target_value) if raw_target_value is not None and bool(pd.notna(raw_target_value)) else 0.0
            ),
        )

    target_value_resolved = bool(pd.notna(raw_target_value))
    target_value = float(raw_target_value) if raw_target_value is not None and target_value_resolved else 0.0

    if not target_value_resolved:
        return {
            "target_value": target_value,
            "target_value_resolved": False,
            "target_read": target_read,
            "offers": [],
            "combos_considered": 0,
            "combos_evaluated": 0,
        }

    your_sellable = sellable_players(your_roster, players, fc_by_sleeper_id, replacement_level, league, byes)
    pool = [
        {"kind": "player", "id": row["player_id"], "label": row["name"], "value": row["adj_value"] or 0.0}
        for _, row in your_sellable.iterrows()
    ]
    your_picks = pick_value_table[pick_value_table["owner_roster_id"] == your_roster["roster_id"]]
    pool += [
        {"kind": "pick", "id": row["pick"], "label": row["pick"], "value": row["value"]}
        for _, row in your_picks.iterrows()
        if bool(pd.notna(row["value"]))
    ]
    if target_value > 0:
        pool = [c for c in pool if c["value"] <= TRADE_OFFER_PREFILTER_HIGH * target_value]
    pool.sort(key=lambda c: c["value"], reverse=True)
    pool = pool[:TRADE_OFFER_POOL_CAP]

    partner_needs = need_positions(roster_needs_summary(partner_roster, players))

    combos_considered = 0
    prefiltered = []
    for size in range(1, TRADE_OFFER_MAX_COMBO_SIZE + 1):
        for combo in itertools.combinations(pool, size):
            combos_considered += 1
            combo_value = sum(c["value"] for c in combo)
            if target_value > 0 and not (
                TRADE_OFFER_PREFILTER_LOW * target_value <= combo_value <= TRADE_OFFER_PREFILTER_HIGH * target_value
            ):
                continue
            prefiltered.append(combo)

    tolerance = max(TRADE_OFFER_PARTNER_TOLERANCE_PCT * target_value, TRADE_OFFER_MIN_ABSOLUTE_TOLERANCE)
    offers = []
    for combo in prefiltered:
        combo_player_ids = [c["id"] for c in combo if c["kind"] == "player"]
        combo_pick_value = sum(c["value"] for c in combo if c["kind"] == "pick")

        if target_player_id:
            your_incoming, your_incoming_pick_value = [target_player_id], 0.0
            partner_outgoing, partner_outgoing_pick_value = [target_player_id], 0.0
        else:
            your_incoming, your_incoming_pick_value = [], target_value
            partner_outgoing, partner_outgoing_pick_value = [], target_value

        your_side = evaluate_trade(
            your_roster, combo_player_ids, your_incoming, players, fc_by_sleeper_id, byes, league,
            outgoing_pick_value=combo_pick_value, incoming_pick_value=your_incoming_pick_value,
        )
        partner_side = evaluate_trade(
            partner_roster, partner_outgoing, combo_player_ids, players, fc_by_sleeper_id, byes, league,
            outgoing_pick_value=partner_outgoing_pick_value, incoming_pick_value=combo_pick_value,
        )
        if partner_side["asset_value_delta"] < -tolerance:
            continue

        partner_need_match = any(
            c["kind"] == "player" and players.get(c["id"], {}).get("position") in partner_needs for c in combo
        )
        offers.append(
            {
                "combo": list(combo),
                "your_side": your_side,
                "partner_side": partner_side,
                "partner_need_match": partner_need_match,
            }
        )

    offers.sort(key=lambda o: (-o["your_side"]["asset_value_delta"], not o["partner_need_match"], len(o["combo"])))

    return {
        "target_value": target_value,
        "target_value_resolved": True,
        "target_read": target_read,
        "offers": offers[:top_n],
        "combos_considered": combos_considered,
        "combos_evaluated": len(prefiltered),
    }
