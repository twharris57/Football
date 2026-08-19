"""Sellable-depth surfacing, two-sided trade evaluation, and the trade-target optimizer."""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from typing import Any

import pandas as pd

from .byes import gap_delta
from .constants import FANTASY_POSITIONS, FLEX_ELIGIBLE_POSITIONS
from .handcuffs import handcuff_targets as handcuff_targets_for
from .lineup import assign_starters, player_value_rows, roster_total_capacity
from .marginal_value import rank_by_marginal_value, recommend_drop, season_average_starter_value
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

# Leaguewide Suggested Trades (RT-15) - how many of the cheap, leaguewide
# marginal-value-ranked candidates get the expensive per-candidate
# find_trade_offers() search. Bounds Stage 2's cost to a constant
# regardless of league size (see leaguewide_trade_candidates()/
# suggested_trades() below), the same order of magnitude as one partner's
# whole-roster scan already was before this feature existed.
SUGGESTED_TRADE_SCAN_TOP_K = 15


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


def _bye_gap_callouts(
    before_roster: dict, after_roster: dict, players: dict[str, dict], byes: dict[str, int], league: dict
) -> list[str]:
    """Weeks this trade newly breaks or newly fixes a dedicated-slot weekly gap.

    Reuses `gap_delta()` in both directions - swapping before/after finds
    the reverse case (a gap that existed before but not after), the same
    primitive `alternate_gap_note`/`sellable_players` already use, just
    read backwards - not a second gap-detection model.
    """
    callouts = []
    worsened = gap_delta(before_roster, after_roster, players, byes, league)
    if not worsened.empty:
        weeks = ", ".join(str(w) for w in worsened["week"])
        callouts.append(f"would open a weekly starting gap in week(s) {weeks}")
    closed = gap_delta(after_roster, before_roster, players, byes, league)
    if not closed.empty:
        weeks = ", ".join(str(w) for w in closed["week"])
        callouts.append(f"would close an existing weekly starting gap in week(s) {weeks}")
    return callouts


def _handcuff_callouts(
    current_ids: list[str],
    outgoing_set: set[str],
    incoming_player_ids: list[str],
    players: dict[str, dict],
    handcuffs: dict[str, str],
) -> list[str]:
    """Incoming players that handcuff one of this roster's own current (kept) RBs."""
    if not handcuffs:
        return []
    keep_ids = [pid for pid in current_ids if pid not in outgoing_set]
    targets = handcuff_targets_for(keep_ids, players, handcuffs)
    return [f"also handcuffs your own {targets[pid]}" for pid in incoming_player_ids if targets.get(pid)]


def _buried_to_starter_callouts(
    current_ids: list[str],
    roster_after_drops: list[str],
    outgoing_player_ids: list[str],
    incoming_player_ids: list[str],
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    ineligible_ids: frozenset[str],
    league: dict,
) -> list[str]:
    """Outgoing players who weren't even starting here, and incoming players who immediately would.

    A genuine mutual-unlock reason a trade can make sense even at close to
    even raw asset value - a bench player is a low real cost for the
    sender to give up, and an instant starter is real value for the
    receiver, neither of which shows up as anything special in the
    lineup/asset deltas alone. Same `assign_starters()` + `ineligible_ids`
    filtering pattern as `recommend_drop()`.
    """

    def _starter_ids(player_ids: list[str]) -> set[str]:
        rows = [r for r in player_value_rows(player_ids, players, fc_by_sleeper_id) if r["player_id"] not in ineligible_ids]
        return {pid for _, pid in assign_starters(rows, league["roster_positions"]) if pid}

    before_starters = _starter_ids(current_ids)
    after_starters = _starter_ids(roster_after_drops)

    callouts = []
    for player_id in outgoing_player_ids:
        if player_id in current_ids and player_id not in before_starters:
            name = players.get(player_id, {}).get("full_name")
            callouts.append(f"{name} wasn't even starting for you")
    for player_id in incoming_player_ids:
        if player_id in after_starters:
            name = players.get(player_id, {}).get("full_name")
            callouts.append(f"{name} would start for you immediately")
    return callouts


def _pick_context_callouts(pick_names: list[str], pick_value_table: pd.DataFrame | None) -> list[str]:
    """Where each involved pick falls in its own class's value ranking, not just a bare number.

    `pick_value_table` is `pick_trade_values()`'s leaguewide output (every
    owner's picks, one row per pick) - ranked here within the pick's own
    season ("class"), not the whole table, so "the #2 pick" means #2 among
    that year's picks specifically. The leading 4-digit year is the only
    season anchor common to both of `pick_trade_values()`'s name formats -
    this season's slot-specific "2026 Pick 1.01" and next season's
    round-only "2027 1st" (no real draft object yet to assign a slot).
    Splitting on " Pick " instead would leave a next-season pick's "season"
    as its own full name, putting it alone in a one-pick class that always
    ranks #1 - fixed after verifying live (RT-18 fix-before-merge review,
    2026-08-07 - see `.claude/conventions/valuation_principles.md`).
    """
    if not pick_names or pick_value_table is None or pick_value_table.empty:
        return []
    ranked = pick_value_table.dropna(subset=["value"]).copy()
    if ranked.empty:
        return []
    # A name with no leading year (never a real pick_trade_values() output,
    # but happens in tests using placeholder pick names) falls back to its
    # own full name as "season" - an isolated one-row group, same graceful
    # degradation a real but literally unparseable name would need, rather
    # than a NaN group that breaks the int cast below.
    ranked["season"] = ranked["pick"].str.extract(r"^(\d{4})")[0].fillna(ranked["pick"])
    ranked["rank"] = ranked.groupby("season")["value"].rank(ascending=False, method="min").astype(int)
    rank_by_pick = dict(zip(ranked["pick"], zip(ranked["rank"], ranked["value"])))
    season_by_pick = dict(zip(ranked["pick"], ranked["season"]))

    callouts = []
    for pick_name in pick_names:
        info = rank_by_pick.get(pick_name)
        if info is None:
            continue
        rank, value = info
        season = season_by_pick.get(pick_name, pick_name)
        callouts.append(f"{pick_name} is currently the #{rank} remaining pick in the {season} class (value {value:.0f})")
    return callouts


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
    handcuffs: dict[str, str] | None = None,
    outgoing_pick_names: list[str] | None = None,
    incoming_pick_names: list[str] | None = None,
    pick_value_table: pd.DataFrame | None = None,
    compute_callouts: bool = True,
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

    `callouts` (RT-18) surfaces non-obvious value the two headline deltas
    can miss - a bye-week gap this trade opens or closes, an incoming
    player who handcuffs one of this roster's own current RBs, an outgoing
    player who was buried on this bench or an incoming one who'd start
    immediately, and where an involved pick ranks in its own class. All
    four compose existing primitives (`gap_delta`, `handcuff_targets`,
    `assign_starters`, `pick_trade_values()`'s output) rather than a new
    signal - see `.claude/conventions/valuation_principles.md`'s "one
    valuation strategy" rule. `handcuffs`/`outgoing_pick_names`/
    `incoming_pick_names`/`pick_value_table` are optional so existing
    callers/tests that don't have pick or handcuff context on hand keep
    working unchanged; omitting them just means those specific callouts
    don't fire. `compute_callouts=False` skips all four entirely (`callouts`
    comes back `[]`) - for a caller like `find_trade_offers()` that runs
    this in a combinatorial search loop and only needs callouts for the
    handful of combos it actually surfaces, computing them for every combo
    explored is pure waste (verified live: ~90% of this function's cost
    with callouts on, for a combo that gets filtered out or ranked below
    `top_n` and never shown).
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

    callouts: list[str] = []
    if compute_callouts:
        after_roster = {**roster, "players": roster_after_drops}
        callouts = (
            _bye_gap_callouts(roster, after_roster, players, byes, league)
            + _handcuff_callouts(current_ids, outgoing_set, incoming_player_ids, players, handcuffs or {})
            + _buried_to_starter_callouts(
                current_ids, roster_after_drops, outgoing_player_ids, incoming_player_ids,
                players, fc_by_sleeper_id, ineligible_ids, league,
            )
            + _pick_context_callouts((outgoing_pick_names or []) + (incoming_pick_names or []), pick_value_table)
        )

    return {
        "lineup_delta": after_value - before_value,
        "lineup_delta_after_drops": after_value_post_drops - before_value,
        "asset_value_delta": incoming_value - outgoing_value,
        "over_capacity": overflow > 0,
        "roster_size_after": len(roster_after),
        "capacity": capacity,
        "recommended_drops": recommended_drops,
        "callouts": callouts,
    }


def _asset_pool(
    roster: dict,
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    replacement_level: dict[str, float],
    league: dict,
    byes: dict[str, int],
    pick_value_table: pd.DataFrame,
    value_cap: float | None = None,
) -> list[dict[str, Any]]:
    """One roster's sellable players plus every pick it owns (current- and
    future-season alike, since `pick_value_table` already carries both
    formats), as a single value-sorted, capped asset pool - each entry
    `{"kind": "player"/"pick", "id", "label", "value"}`.

    The shared candidate-pool builder `find_trade_offers()`'s combo search
    and `improve_incoming_offer()`'s neighbor search both draw from, so a
    heterogeneous mix (players and picks together) is handled uniformly by
    every consumer rather than each reimplementing its own merge. `value_cap`
    (if given) drops any asset priced beyond it up front - no combo/variant
    containing one could ever land in a target-anchored value band.
    """
    sellable = sellable_players(roster, players, fc_by_sleeper_id, replacement_level, league, byes)
    pool = [
        {
            "kind": "player",
            "id": row["player_id"],
            "label": row["name"],
            "value": row["adj_value"] if pd.notna(row["adj_value"]) else 0.0,
        }
        for _, row in sellable.iterrows()
    ]
    owned_picks = pick_value_table[pick_value_table["owner_roster_id"] == roster["roster_id"]]
    pool += [
        {"kind": "pick", "id": row["pick"], "label": row["pick"], "value": row["value"]}
        for _, row in owned_picks.iterrows()
        if pd.notna(row["value"])
    ]
    if value_cap is not None:
        pool = [c for c in pool if c["value"] <= value_cap]
    pool.sort(key=lambda c: c["value"], reverse=True)
    return pool[:TRADE_OFFER_POOL_CAP]


def find_trade_offers(
    your_roster: dict,
    partner_roster: dict,
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    byes: dict[str, int],
    league: dict,
    replacement_level: dict[str, float],
    pick_value_table: pd.DataFrame,
    handcuffs: dict[str, str] | None = None,
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
    alternatives, as a tiebreaker only - each offer's `partner_need_match`
    (bool) and `partner_need_positions` (which position(s) specifically)
    reflect this. Ranked best-for-you first, then need-match, then fewest
    assets. Returns up to `top_n`, empty if nothing clears the bar.

    `combos_considered`/`combos_evaluated` are the raw and post-prefilter
    combo counts, so an empty result can say something concrete.

    `handcuffs` and `pick_value_table` pass straight through to every
    `evaluate_trade()` call for its `callouts` (RT-18) - `pick_value_table`
    is already required here for offer search, so it's reused rather than
    a second lookup table.
    """
    if bool(target_player_id) == bool(target_pick_name):
        raise ValueError("Exactly one of target_player_id or target_pick_name must be given.")

    pick_value_by_name = dict(zip(pick_value_table["pick"], pick_value_table["value"]))

    if target_player_id:
        target_entry = fc_by_sleeper_id.get(target_player_id)
        raw_target_value = target_entry.get("adj_value") if target_entry else None
        target_read = evaluate_trade(
            your_roster, [], [target_player_id], players, fc_by_sleeper_id, byes, league, handcuffs=handcuffs
        )
    else:
        raw_target_value = pick_value_by_name.get(target_pick_name)
        target_read = evaluate_trade(
            your_roster, [], [], players, fc_by_sleeper_id, byes, league,
            incoming_pick_value=float(raw_target_value) if pd.notna(raw_target_value) else 0.0,
            handcuffs=handcuffs, incoming_pick_names=[target_pick_name], pick_value_table=pick_value_table,
        )

    target_value_resolved = pd.notna(raw_target_value)
    target_value = float(raw_target_value) if target_value_resolved else 0.0

    if not target_value_resolved:
        return {
            "target_value": target_value,
            "target_value_resolved": False,
            "target_read": target_read,
            "offers": [],
            "combos_considered": 0,
            "combos_evaluated": 0,
        }

    pool = _asset_pool(
        your_roster,
        players,
        fc_by_sleeper_id,
        replacement_level,
        league,
        byes,
        pick_value_table,
        value_cap=TRADE_OFFER_PREFILTER_HIGH * target_value if target_value > 0 else None,
    )

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

    def _evaluate_combo(combo: Sequence[dict], compute_callouts: bool) -> tuple[dict, dict]:
        combo_player_ids = [c["id"] for c in combo if c["kind"] == "player"]
        combo_pick_names = [c["id"] for c in combo if c["kind"] == "pick"]
        combo_pick_value = sum(c["value"] for c in combo if c["kind"] == "pick")

        if target_player_id:
            your_incoming, your_incoming_pick_value, your_incoming_pick_names = [target_player_id], 0.0, []
            partner_outgoing, partner_outgoing_pick_value, partner_outgoing_pick_names = [target_player_id], 0.0, []
        else:
            your_incoming, your_incoming_pick_value, your_incoming_pick_names = [], target_value, [target_pick_name]
            partner_outgoing, partner_outgoing_pick_value = [], target_value
            partner_outgoing_pick_names = [target_pick_name]

        your_side = evaluate_trade(
            your_roster, combo_player_ids, your_incoming, players, fc_by_sleeper_id, byes, league,
            outgoing_pick_value=combo_pick_value, incoming_pick_value=your_incoming_pick_value,
            handcuffs=handcuffs, outgoing_pick_names=combo_pick_names, incoming_pick_names=your_incoming_pick_names,
            pick_value_table=pick_value_table, compute_callouts=compute_callouts,
        )
        partner_side = evaluate_trade(
            partner_roster, partner_outgoing, combo_player_ids, players, fc_by_sleeper_id, byes, league,
            outgoing_pick_value=partner_outgoing_pick_value, incoming_pick_value=combo_pick_value,
            handcuffs=handcuffs, outgoing_pick_names=partner_outgoing_pick_names, incoming_pick_names=combo_pick_names,
            pick_value_table=pick_value_table, compute_callouts=compute_callouts,
        )
        return your_side, partner_side

    tolerance = max(TRADE_OFFER_PARTNER_TOLERANCE_PCT * target_value, TRADE_OFFER_MIN_ABSOLUTE_TOLERANCE)
    offers = []
    for combo in prefiltered:
        # compute_callouts=False here: this loop runs for every prefiltered
        # combo just to filter/rank them, and only `top_n` ever get shown -
        # computing full callouts (bye-gap/handcuff/buried-bench/pick-rank)
        # for every one of them was ~90% of this search's cost for value no
        # caller ever saw. Recomputed with callouts on, below, for only the
        # combos that actually make the cut.
        your_side, partner_side = _evaluate_combo(combo, compute_callouts=False)
        if partner_side["asset_value_delta"] < -tolerance:
            continue

        partner_need_positions = frozenset(
            players.get(c["id"], {}).get("position")
            for c in combo
            if c["kind"] == "player" and players.get(c["id"], {}).get("position") in partner_needs
        )
        offers.append(
            {
                "combo": list(combo),
                "your_side": your_side,
                "partner_side": partner_side,
                "partner_need_match": bool(partner_need_positions),
                "partner_need_positions": partner_need_positions,
            }
        )

    offers.sort(key=lambda o: (-o["your_side"]["asset_value_delta"], not o["partner_need_match"], len(o["combo"])))
    offers = offers[:top_n]
    for offer in offers:
        offer["your_side"], offer["partner_side"] = _evaluate_combo(offer["combo"], compute_callouts=True)

    return {
        "target_value": target_value,
        "target_value_resolved": True,
        "target_read": target_read,
        "offers": offers,
        "combos_considered": combos_considered,
        "combos_evaluated": len(prefiltered),
    }


def _is_good(your_side: dict[str, Any]) -> bool:
    """Worth surfacing at all - the same lineup-value bar `suggested_trades()`
    already established (`.claude/conventions/valuation_principles.md`'s
    "worth surfacing" filter rule), reused here rather than a second bar for
    "is this actually a good trade."
    """
    return your_side["lineup_delta_after_drops"] > 0


def improve_incoming_offer(
    your_roster: dict,
    partner_roster: dict,
    your_outgoing_player_ids: list[str],
    your_outgoing_pick_names: list[str],
    incoming_player_ids: list[str],
    incoming_pick_names: list[str],
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    byes: dict[str, int],
    league: dict,
    replacement_level: dict[str, float],
    pick_value_table: pd.DataFrame,
    handcuffs: dict[str, str] | None = None,
    top_n: int = 3,
) -> dict[str, Any]:
    """Evaluate a trade a partner has already proposed to us (RT-14) - both
    sides already fully specified, unlike `find_trade_offers()`'s single
    target - and either confirm it's worth taking, suggest a nearby
    adjustment that would make it worth taking, or say plainly that no
    adjustment found does. Returns `{"verdict": "accept"/"counter"/"reject",
    "baseline": {...}, "improvements": [...]}`.

    Deliberately not another from-scratch `find_trade_offers()`-style combo
    search - the ask here is "tweak this specific real proposal," not
    "ignore it and search my whole pool again." Generates single-move
    neighbors of the proposed trade (drop an asset, swap one for a pool
    candidate, add a pool candidate) independently on each side - your own
    `_asset_pool()` for what you'd give, the partner's for what you'd
    receive, so a heterogeneous mix (players, current- or future-season
    picks) on either side is handled uniformly, not as a special case. This
    stays linear in (assets on a side) x (pool size), not combinatorial, so
    it doesn't need `find_trade_offers()`'s prefilter/combo-count machinery.

    A variant survives only if it clears both of the same gates already
    established elsewhere in this module: the partner's own
    `asset_value_delta` within `TRADE_OFFER_PARTNER_TOLERANCE_PCT`/
    `TRADE_OFFER_MIN_ABSOLUTE_TOLERANCE` of zero (anchored to the proposal's
    own incoming value, mirroring `find_trade_offers()`'s tolerance
    formula), and `_is_good()` in absolute terms - not merely "better than
    an already-bad baseline." Nothing needs to separately forbid a
    one-sided giveaway (e.g. dropping your only outgoing asset): that fails
    the partner-tolerance gate on its own.

    Verdict logic:
    - `"accept"` - the baseline proposal, exactly as offered, already
      clears `_is_good()`. `improvements` still lists any variant that's
      *also* good and strictly better than baseline, as optional upside.
    - `"counter"` - the baseline doesn't clear the bar, but at least one
      neighbor variant clears both gates. `improvements` is that ranked,
      `top_n`-capped list (best `your_side["asset_value_delta"]` first,
      same key `find_trade_offers()` ranks by).
    - `"reject"` - the baseline doesn't clear the bar and no variant does
      either. `improvements` is always `[]` in this case.

    `compute_callouts=False` while generating/filtering every variant,
    recomputed `True` only for the survivors actually returned - identical
    perf pattern to `find_trade_offers()`'s own combo search.
    """
    pick_value_by_name = dict(zip(pick_value_table["pick"], pick_value_table["value"]))

    def _pick_value_sum(pick_names: list[str]) -> float:
        return sum(float(v) for v in (pick_value_by_name.get(name) for name in pick_names) if pd.notna(v))

    def _player_asset(player_id: str) -> dict[str, Any]:
        info = players.get(player_id, {})
        entry = fc_by_sleeper_id.get(player_id)
        value = entry.get("adj_value") if entry else None
        return {"kind": "player", "id": player_id, "label": info.get("full_name"), "value": value if pd.notna(value) else 0.0}

    def _pick_asset(pick_name: str) -> dict[str, Any]:
        value = pick_value_by_name.get(pick_name)
        return {"kind": "pick", "id": pick_name, "label": pick_name, "value": value if pd.notna(value) else 0.0}

    def _evaluate(
        out_player_ids: list[str], out_pick_names: list[str], in_player_ids: list[str], in_pick_names: list[str],
        compute_callouts: bool,
    ) -> tuple[dict, dict]:
        out_pick_value = _pick_value_sum(out_pick_names)
        in_pick_value = _pick_value_sum(in_pick_names)
        your_side = evaluate_trade(
            your_roster, out_player_ids, in_player_ids, players, fc_by_sleeper_id, byes, league,
            outgoing_pick_value=out_pick_value, incoming_pick_value=in_pick_value,
            handcuffs=handcuffs, outgoing_pick_names=out_pick_names, incoming_pick_names=in_pick_names,
            pick_value_table=pick_value_table, compute_callouts=compute_callouts,
        )
        partner_side = evaluate_trade(
            partner_roster, in_player_ids, out_player_ids, players, fc_by_sleeper_id, byes, league,
            outgoing_pick_value=in_pick_value, incoming_pick_value=out_pick_value,
            handcuffs=handcuffs, outgoing_pick_names=in_pick_names, incoming_pick_names=out_pick_names,
            pick_value_table=pick_value_table, compute_callouts=compute_callouts,
        )
        return your_side, partner_side

    def _neighbor_variants(owner_roster: dict, current_player_ids: list[str], current_pick_names: list[str], exclude_ids: set[str]) -> list[dict]:
        """Single-move (drop/swap/add) neighbors of one side of the proposed
        trade, drawing swap/add candidates from `owner_roster`'s own asset
        pool - your pool for what you'd give, the partner's for what you'd
        receive. `exclude_ids` keeps a candidate from duplicating an asset
        already present anywhere in the trade."""
        pool = _asset_pool(owner_roster, players, fc_by_sleeper_id, replacement_level, league, byes, pick_value_table)
        candidates = [c for c in pool if c["id"] not in exclude_ids]
        current_assets = [_player_asset(pid) for pid in current_player_ids] + [_pick_asset(pn) for pn in current_pick_names]

        variants = []
        for asset in current_assets:
            remaining_players = [pid for pid in current_player_ids if pid != asset["id"]]
            remaining_picks = [pn for pn in current_pick_names if pn != asset["id"]]
            variants.append({"move": "drop", "removed": asset, "added": None, "player_ids": remaining_players, "pick_names": remaining_picks})
            for candidate in candidates:
                swapped_players = remaining_players + [candidate["id"]] if candidate["kind"] == "player" else remaining_players
                swapped_picks = remaining_picks + [candidate["id"]] if candidate["kind"] == "pick" else remaining_picks
                variants.append({"move": "swap", "removed": asset, "added": candidate, "player_ids": swapped_players, "pick_names": swapped_picks})
        for candidate in candidates:
            added_players = list(current_player_ids) + [candidate["id"]] if candidate["kind"] == "player" else list(current_player_ids)
            added_picks = list(current_pick_names) + [candidate["id"]] if candidate["kind"] == "pick" else list(current_pick_names)
            variants.append({"move": "add", "removed": None, "added": candidate, "player_ids": added_players, "pick_names": added_picks})
        return variants

    baseline_your, baseline_partner = _evaluate(
        your_outgoing_player_ids, your_outgoing_pick_names, incoming_player_ids, incoming_pick_names, compute_callouts=True
    )
    baseline = {"your_side": baseline_your, "partner_side": baseline_partner}

    incoming_value = sum(_player_asset(pid)["value"] for pid in incoming_player_ids) + _pick_value_sum(incoming_pick_names)
    tolerance = max(TRADE_OFFER_PARTNER_TOLERANCE_PCT * incoming_value, TRADE_OFFER_MIN_ABSOLUTE_TOLERANCE)

    already_in_trade = set(your_outgoing_player_ids) | set(your_outgoing_pick_names) | set(incoming_player_ids) | set(incoming_pick_names)
    your_variants = _neighbor_variants(your_roster, your_outgoing_player_ids, your_outgoing_pick_names, already_in_trade)
    their_variants = _neighbor_variants(partner_roster, incoming_player_ids, incoming_pick_names, already_in_trade)

    candidates = [(v, "yours") for v in your_variants] + [(v, "theirs") for v in their_variants]

    survivors = []
    for variant, side in candidates:
        if side == "yours":
            out_players, out_picks = variant["player_ids"], variant["pick_names"]
            in_players, in_picks = incoming_player_ids, incoming_pick_names
        else:
            out_players, out_picks = your_outgoing_player_ids, your_outgoing_pick_names
            in_players, in_picks = variant["player_ids"], variant["pick_names"]

        your_side, partner_side = _evaluate(out_players, out_picks, in_players, in_picks, compute_callouts=False)
        if partner_side["asset_value_delta"] < -tolerance:
            continue
        if not _is_good(your_side):
            continue
        survivors.append(
            {
                "move": variant["move"],
                "side": side,
                "removed": variant["removed"],
                "added": variant["added"],
                "your_side": your_side,
                "partner_side": partner_side,
                "_out_players": out_players,
                "_out_picks": out_picks,
                "_in_players": in_players,
                "_in_picks": in_picks,
            }
        )

    survivors.sort(key=lambda s: s["your_side"]["asset_value_delta"], reverse=True)
    top = survivors[:top_n]
    for survivor in top:
        survivor["your_side"], survivor["partner_side"] = _evaluate(
            survivor["_out_players"], survivor["_out_picks"], survivor["_in_players"], survivor["_in_picks"], compute_callouts=True
        )
        del survivor["_out_players"], survivor["_out_picks"], survivor["_in_players"], survivor["_in_picks"]

    if _is_good(baseline_your):
        verdict = "accept"
        improvements = [s for s in top if s["your_side"]["asset_value_delta"] > baseline_your["asset_value_delta"]]
    elif top:
        verdict = "counter"
        improvements = top
    else:
        verdict = "reject"
        improvements = []

    return {"verdict": verdict, "baseline": baseline, "improvements": improvements}


def _max_affordable_target_value(sellable: pd.DataFrame, pick_value_table: pd.DataFrame, roster_id: int) -> float:
    """Rough ceiling on a target's market value this roster's own sellable pool could plausibly match.

    Mirrors `find_trade_offers()`'s own `TRADE_OFFER_PREFILTER_HIGH` band (a
    combo priced beyond that multiple of the target's value could never
    land in-band) - reuses that existing tolerance rule rather than adding
    a second one. Used by `leaguewide_trade_candidates()` to keep a
    leaguewide scan's limited search budget off targets no realistic offer
    could ever reach, not to replace `find_trade_offers()`'s own combo
    search - this is a cheap top-line estimate (top
    `TRADE_OFFER_MAX_COMBO_SIZE` assets by value, no combinatorics), not a
    guarantee any specific combo actually clears the bar. `sellable` can be
    a columnless empty DataFrame (`sellable_players()`'s empty-pool shape,
    same trap noted in `summary.py`'s `_sellable_lines`) when there's
    nothing sellable at all - guarded explicitly rather than indexing
    `"adj_value"` directly, which would raise `KeyError` on that shape.
    """
    values = sellable["adj_value"].dropna().tolist() if not sellable.empty else []
    values += pick_value_table.loc[pick_value_table["owner_roster_id"] == roster_id, "value"].dropna().tolist()
    top_combo = sorted(values, reverse=True)[:TRADE_OFFER_MAX_COMBO_SIZE]
    return TRADE_OFFER_PREFILTER_HIGH * sum(top_combo)


def leaguewide_trade_candidates(
    rosters: list[dict],
    user_roster: dict,
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    byes: dict[str, int],
    league: dict,
    sellable: pd.DataFrame,
    pick_value_table: pd.DataFrame,
    top_n: int = SUGGESTED_TRADE_SCAN_TOP_K,
) -> list[dict]:
    """Cheap, leaguewide "worth pursuing" pre-rank - Stage 1 of Suggested Trades (RT-15).

    Every fantasy-relevant player on every *other* roster is a candidate.
    Reuses `rank_by_marginal_value()` exactly like `free_agent_board()`
    does - not a second valuation model (see
    `.claude/conventions/valuation_principles.md`) - just a different
    candidate pool source (other rosters instead of the free-agent pool).

    Pre-filtered by `_max_affordable_target_value()` before ranking:
    without this, the top marginal-value candidates leaguewide skew toward
    the biggest names at your weak positions - exactly the players no
    realistic offer from your own sellable depth could match. Left
    unfiltered, `suggested_trades()`'s downstream expensive search (capped
    to this function's `top_n`) would waste its whole budget on
    unreachable stars instead of genuinely gettable value, since a
    marginal-value read alone has no notion of affordability.

    Filtered to `marginal_value > 0` (matches `free_agent_board`/
    `pickup_alerts`' existing "worth surfacing at all" convention). Returns
    up to `top_n` rows (`player_id`, `marginal_value`, `drop`, `roster_id`)
    sorted best first - `roster_id` (the one field `free_agent_board`'s row
    shape doesn't need) is which partner owns the candidate, for
    `suggested_trades()` to search against.
    """
    ineligible_ids = frozenset(user_roster.get("taxi") or []) | frozenset(user_roster.get("reserve") or [])
    reserve_filled = len(user_roster.get("reserve") or [])
    taxi_filled = len(user_roster.get("taxi") or [])

    ceiling = _max_affordable_target_value(sellable, pick_value_table, user_roster["roster_id"])

    owner_by_player_id: dict[str, int] = {}
    for roster in rosters:
        if roster["roster_id"] == user_roster["roster_id"]:
            continue
        for player_id, _info in roster_fantasy_players(roster, players):
            owner_by_player_id[player_id] = roster["roster_id"]

    def _affordable(player_id: str) -> bool:
        entry = fc_by_sleeper_id.get(player_id)
        value = entry.get("adj_value") if entry else None
        return pd.isna(value) or value <= ceiling

    candidate_ids = [pid for pid in owner_by_player_id if _affordable(pid)]

    ranked = rank_by_marginal_value(
        candidate_ids,
        list(user_roster.get("players") or []),
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

    return [
        {**candidate, "roster_id": owner_by_player_id[candidate["player_id"]]}
        for candidate in ranked
        if candidate["marginal_value"] > 0
    ]


def suggested_trades(
    your_roster: dict,
    rosters_by_id: dict[int, dict],
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    byes: dict[str, int],
    league: dict,
    replacement_level: dict[str, float],
    pick_value_table: pd.DataFrame,
    candidates: list[dict],
    handcuffs: dict[str, str] | None = None,
    top_n: int = 3,
) -> list[dict]:
    """Stage 2 of Suggested Trades (RT-15): the real offer search, only for Stage 1's short list.

    `candidates` is typically `leaguewide_trade_candidates()`'s output -
    already capped to a small K, which is what keeps this affordable at
    leaguewide scale (see that function's and this module's own docstrings
    for the cost reasoning). For each candidate, resolves which roster owns
    them and runs the **existing, unmodified** `find_trade_offers()` -
    zero new valuation logic, this function only orchestrates and ranks.

    Candidates with no viable offer (`find_trade_offers()`'s `offers` comes
    back empty - nothing clears the partner's plausibility bar) are dropped
    entirely rather than shown empty. A viable offer still isn't necessarily
    a good one for the user - `find_trade_offers()`'s only hard gate is the
    *partner's* `asset_value_delta` staying in tolerance, nothing about the
    user's own lineup impact - so survivors are further filtered to a
    positive best-offer `your_side["lineup_delta_after_drops"]` (matches
    `leaguewide_trade_candidates()`'s own `marginal_value > 0` "worth
    surfacing at all" filter one stage earlier; see
    `.claude/conventions/valuation_principles.md`'s "worth surfacing" filter
    rule) before being ranked by that same number - the same number
    `_show_trade_side()` already surfaces per offer today, not a new
    metric - and capped to `top_n`. Each returned entry is a
    `find_trade_offers()` result dict with `roster_id`/`target_player_id`
    added, so a caller can label which partner owns the suggestion.
    """
    results = []
    for candidate in candidates:
        partner_roster = rosters_by_id[candidate["roster_id"]]
        offer_result = find_trade_offers(
            your_roster,
            partner_roster,
            players,
            fc_by_sleeper_id,
            byes,
            league,
            replacement_level,
            pick_value_table,
            handcuffs=handcuffs,
            target_player_id=candidate["player_id"],
        )
        if offer_result["offers"] and offer_result["offers"][0]["your_side"]["lineup_delta_after_drops"] > 0:
            results.append(
                {**offer_result, "roster_id": candidate["roster_id"], "target_player_id": candidate["player_id"]}
            )

    results.sort(key=lambda r: r["offers"][0]["your_side"]["lineup_delta_after_drops"], reverse=True)
    return results[:top_n]
