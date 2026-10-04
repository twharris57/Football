"""Sellable depth, two-sided trade evaluation, and trade-offer search."""

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

# Offer-search bounds. Judgment calls sized for ~12 teams with 5-15 sellable assets each.
TRADE_OFFER_POOL_CAP = 12
TRADE_OFFER_MAX_COMBO_SIZE = 3
TRADE_OFFER_PREFILTER_LOW = 0.5
TRADE_OFFER_PREFILTER_HIGH = 2.0
TRADE_OFFER_PARTNER_TOLERANCE_PCT = 0.15
TRADE_OFFER_MIN_ABSOLUTE_TOLERANCE = 25.0

# Suggested Trades: how many stage-1 candidates get the expensive offer search.
SUGGESTED_TRADE_SCAN_TOP_K = 15


def sellable_players(
    roster: dict,
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    replacement_level: dict[str, float],
    league: dict,
    byes: dict[str, int],
) -> pd.DataFrame:
    """Bench depth worth shopping, sorted by `adj_value`.

    Only at positions with `vor > 0`; reserves FLEX-eligible depth; keeps anyone whose
    removal opens a weekly gap; excludes rookies and starters. `player_id` is a join key
    — drop it before rendering.
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


def _weekly_gap_changes(
    before_roster: dict, after_roster: dict, players: dict[str, dict], byes: dict[str, int], league: dict
) -> tuple[list[int], list[int]]:
    """`(weeks newly broken, weeks newly fixed)`, via `gap_delta()` in both directions."""
    worsened = gap_delta(before_roster, after_roster, players, byes, league)
    closed = gap_delta(after_roster, before_roster, players, byes, league)
    return sorted(worsened["week"].tolist()), sorted(closed["week"].tolist())


def _weekly_gap_callouts(weekly_gaps_opened: list[int], weekly_gaps_closed: list[int]) -> list[str]:
    """Format `_weekly_gap_changes()` output as callout text."""
    callouts = []
    if weekly_gaps_opened:
        weeks = ", ".join(str(w) for w in weekly_gaps_opened)
        callouts.append(f"would open a weekly starting gap in week(s) {weeks}")
    if weekly_gaps_closed:
        weeks = ", ".join(str(w) for w in weekly_gaps_closed)
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
    """Outgoing players who weren't starting here; incoming players who would start at once."""

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
    """Each pick's rank within its own draft class.

    The class comes from the leading year, the one anchor common to both name formats
    ("2026 Pick 1.01", "2027 1st").
    """
    if not pick_names or pick_value_table is None or pick_value_table.empty:
        return []
    ranked = pick_value_table.dropna(subset=["value"]).copy()
    if ranked.empty:
        return []
    # No leading year (test placeholder names): group by the full name.
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
    """Evaluate one side of a multi-asset trade for one roster.

    - `lineup_delta`: season-average lineup value after vs. before.
    - `asset_value_delta`: summed `adj_value` + pick values.
    - Over capacity, `recommend_drop()` cuts one player per overflow (never an incoming
      one); `lineup_delta_after_drops` includes those cuts.
    - `weekly_gaps_opened`/`weekly_gaps_closed` are always computed (offer ranking
      uses them).
    - `callouts` need the optional handcuff/pick arguments; `compute_callouts=False`
      skips them (~90% of the cost in search loops).

    New players can't use an open taxi slot. The other side is the same call with the
    arguments swapped.
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

    after_roster = {**roster, "players": roster_after_drops}
    weekly_gaps_opened, weekly_gaps_closed = _weekly_gap_changes(roster, after_roster, players, byes, league)

    callouts: list[str] = []
    if compute_callouts:
        callouts = (
            _weekly_gap_callouts(weekly_gaps_opened, weekly_gaps_closed)
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
        "weekly_gaps_opened": weekly_gaps_opened,
        "weekly_gaps_closed": weekly_gaps_closed,
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
    """One roster's sellable players plus owned picks, sorted by value and capped.

    Entries are `{kind, id, label, value}`. Assets above `value_cap` are dropped.
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
    """For one target asset on `partner_roster`, search for offers the partner would plausibly accept.

    Give exactly one of `target_player_id`/`target_pick_name`. `target_read` is the value
    of acquiring it for free. No search runs if the target's value doesn't resolve.

    `offers` are 1-`TRADE_OFFER_MAX_COMBO_SIZE` asset combos from your pool, kept only
    when the partner's asset delta is within tolerance. They're ranked by your asset
    delta, then partner need match, then fewest assets; up to `top_n`. The combo counts
    explain an empty result.
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
        # Callouts are recomputed below only for the combos that get returned.
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
    """Worth surfacing: positive `lineup_delta_after_drops`."""
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
    """Judge a fully specified incoming proposal and look for single-move tweaks.

    Tries drop/swap/add on each side, drawing from that side's asset pool. A variant
    must pass the partner tolerance and `_is_good()`. The tolerance anchors on whichever
    side isn't changing.

    Returns `{"verdict", "baseline", "improvements"}`:
    - `accept`: the baseline is good; improvements are optional upside.
    - `counter`: some variant is good; ranked by your asset delta, up to `top_n`.
    - `reject`: nothing is good; no improvements.
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
        """Drop/swap/add neighbors for one side; `exclude_ids` prevents duplicate assets."""
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

    # Anchor tolerance on the fixed side: incoming value for "yours" variants, outgoing for "theirs".
    incoming_value = sum(_player_asset(pid)["value"] for pid in incoming_player_ids) + _pick_value_sum(incoming_pick_names)
    outgoing_value = sum(_player_asset(pid)["value"] for pid in your_outgoing_player_ids) + _pick_value_sum(your_outgoing_pick_names)
    tolerance_by_side = {
        "yours": max(TRADE_OFFER_PARTNER_TOLERANCE_PCT * incoming_value, TRADE_OFFER_MIN_ABSOLUTE_TOLERANCE),
        "theirs": max(TRADE_OFFER_PARTNER_TOLERANCE_PCT * outgoing_value, TRADE_OFFER_MIN_ABSOLUTE_TOLERANCE),
    }

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
        if partner_side["asset_value_delta"] < -tolerance_by_side[side]:
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
    """Rough ceiling on a target value this roster's top sellable assets could match.

    Uses `find_trade_offers()`'s prefilter band. `sellable` may be a columnless empty frame.
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
    """Suggested Trades stage 1: other teams' players ranked by marginal value.

    Filtered to what your sellable pool can afford and to `marginal_value > 0`, so the
    expensive stage 2 isn't spent on stars you can't reach. Rows include the owning
    `roster_id`.
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
    """Suggested Trades stage 2: run `find_trade_offers()` for each candidate.

    Keeps candidates whose best offer has positive `lineup_delta_after_drops`, ranked by
    it, with net weekly gaps closed as the tiebreaker. Up to `top_n`, each tagged with
    `roster_id`/`target_player_id`.
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

    def _rank_key(result: dict) -> tuple[float, int]:
        your_side = result["offers"][0]["your_side"]
        net_gap_improvement = len(your_side["weekly_gaps_closed"]) - len(your_side["weekly_gaps_opened"])
        return your_side["lineup_delta_after_drops"], net_gap_improvement

    results.sort(key=_rank_key, reverse=True)
    return results[:top_n]
