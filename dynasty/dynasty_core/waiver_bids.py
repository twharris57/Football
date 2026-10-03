"""FAAB bid guidance from this league's real winning waiver bids (`status == "complete"`)."""

from __future__ import annotations

import statistics
from typing import Any

import pandas as pd

from .constants import FANTASY_POSITIONS

# Judgment calls. K comparables, the same-position minimum before broadening, the
# minimum sample before showing anything, and a max value distance of
# max(pct * value, absolute floor).
COMPARABLE_NEAREST_K = 5
MIN_SAME_POSITION = 3
MIN_COMPARABLE_SAMPLE = 3
COMPARABLE_MAX_DISTANCE_PCT = 0.5
COMPARABLE_MIN_ABSOLUTE_DISTANCE = 50.0


def won_bid_sample(
    transactions: list[dict[str, Any]], players: dict[str, dict], fc_by_sleeper_id: dict[str, dict]
) -> pd.DataFrame:
    """Winning bids with the player's position and *current* `adj_value`.

    Current value stands in for value at bid time, which isn't stored. Players without a
    position or value are dropped. Columns: `player_id`, `position`, `adj_value`, `bid`.
    """
    rows = []
    for txn in transactions:
        if txn.get("type") != "waiver" or txn.get("status") != "complete":
            continue
        bid = (txn.get("settings") or {}).get("waiver_bid")
        if bid is None:
            continue
        for player_id in txn.get("adds") or {}:
            info = players.get(player_id, {})
            position = info.get("position")
            if position not in FANTASY_POSITIONS:
                continue
            fc_entry = fc_by_sleeper_id.get(player_id)
            adj_value = fc_entry.get("adj_value") if fc_entry else None
            if adj_value is None or pd.isna(adj_value):
                continue
            rows.append({"player_id": player_id, "position": position, "adj_value": adj_value, "bid": bid})
    return pd.DataFrame(rows, columns=["player_id", "position", "adj_value", "bid"])


def nearest_comparable_bids(
    candidate_adj_value: float,
    candidate_position: str,
    sample: pd.DataFrame,
    k: int = COMPARABLE_NEAREST_K,
    min_same_position: int = MIN_SAME_POSITION,
) -> tuple[list[dict[str, float]], bool]:
    """Up to `k` winning bids nearest `candidate_adj_value`, within the distance floor.

    Same position preferred, broadening to all positions below `min_same_position`. QB
    never mixes with other positions in either direction (superflex prices QBs
    differently). Returns `(comparables, same_position)`; comparables include each bid's
    `adj_value`.
    """
    if sample.empty:
        return [], True

    same_position = sample[sample["position"] == candidate_position]
    if candidate_position == "QB" or len(same_position) >= min_same_position:
        pool, used_same_position = same_position, True
    else:
        pool, used_same_position = sample[sample["position"] != "QB"], False

    distances = (pool["adj_value"] - candidate_adj_value).abs()
    tolerance = max(COMPARABLE_MAX_DISTANCE_PCT * candidate_adj_value, COMPARABLE_MIN_ABSOLUTE_DISTANCE)
    within_tolerance = pool.assign(_distance=distances)
    within_tolerance = within_tolerance[within_tolerance["_distance"] <= tolerance]
    nearest = within_tolerance.sort_values("_distance").head(k)
    return nearest[["bid", "adj_value"]].to_dict("records"), used_same_position


def bid_guidance(candidate_adj_value: float, candidate_position: str, sample: pd.DataFrame) -> dict[str, Any] | None:
    """Comparable bids plus low/median/high from that same list.

    `None` below `MIN_COMPARABLE_SAMPLE` close comparables. Low/high are min/max, not
    percentiles.
    """
    comparables, same_position = nearest_comparable_bids(candidate_adj_value, candidate_position, sample)
    if len(comparables) < MIN_COMPARABLE_SAMPLE:
        return None
    bids = sorted(c["bid"] for c in comparables)
    return {
        "comparables": sorted(comparables, key=lambda c: c["bid"]),
        "low": min(bids),
        "median": statistics.median(bids),
        "high": max(bids),
        "same_position": same_position,
    }
