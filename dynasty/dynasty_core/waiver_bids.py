"""FAAB bid guidance from this league's own real waiver transaction history (RT-10).

Sleeper's transaction log records every waiver claim, win or lose, with the
actual dollar amount bid (`settings.waiver_bid`) - a real, this-league-
specific market signal, not an invented formula. `status == "complete"`
means that bid actually won the player; a `"failed"` bid (outbid, over
budget) never cleared the market, so it isn't a real clearing price and is
excluded from the calibration sample.
"""

from __future__ import annotations

import statistics
from typing import Any

import pandas as pd

from .constants import FANTASY_POSITIONS

# Judgment calls, not derived from any league rule - same status as the
# trade-search bounds in trade.py. k=5 keeps the comparable set small
# enough that "recent winning bids for similar players" reads as a short,
# concrete list, not a wall of numbers. min_same_position=3 is the point
# below which "closest same-position bids" stops being a meaningful sample
# and broadening to every position (still nearest-by-value) is more honest
# than pretending 1-2 points says something about this position
# specifically. MIN_COMPARABLE_SAMPLE=3 is the floor below which no
# guidance is shown at all, rather than a range computed from 1-2 points.
COMPARABLE_NEAREST_K = 5
MIN_SAME_POSITION = 3
MIN_COMPARABLE_SAMPLE = 3


def won_bid_sample(
    transactions: list[dict[str, Any]], players: dict[str, dict], fc_by_sleeper_id: dict[str, dict]
) -> pd.DataFrame:
    """Every real FAAB bid that actually won a player, with that player's
    position and *current* `adj_value` - not value at the time of the bid,
    which isn't reconstructable without historical roster/value snapshots
    this project doesn't keep (a documented simplification, reasonable for
    the short in-season windows this covers - see RT-25 in
    `.claude/PROJECT_PLAN.md` for why this gets materially less accurate
    over a longer, multi-season lookback and needs revisiting before this
    extends that far).

    A player with no resolvable current position or `adj_value` is
    excluded - their bid amount is still real, but not usable as a
    value-based comparable without a value to compare against. Columns:
    `player_id`, `position`, `adj_value`, `bid`.
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
) -> tuple[list[float], bool]:
    """Up to `k` real historical winning bids nearest to `candidate_adj_value`
    by value distance - not a fixed percentage band, which can return
    nothing at all on a thin sample; nearest-K always returns something as
    long as `sample` has any rows.

    Same-position rows preferred; broadens to every row in `sample`
    (still nearest-by-value) only when the same-position count is below
    `min_same_position`, since bidding behavior plausibly differs
    meaningfully by position. Returns `(bids, same_position)` -
    `same_position` is `False` when broadening happened, so a caller can
    say so honestly rather than implying a position-specific comparison
    that isn't really there.
    """
    if sample.empty:
        return [], True

    same_position = sample[sample["position"] == candidate_position]
    if len(same_position) >= min_same_position:
        pool, used_same_position = same_position, True
    else:
        pool, used_same_position = sample, False

    distances = (pool["adj_value"] - candidate_adj_value).abs()
    nearest = pool.assign(_distance=distances).sort_values("_distance").head(k)
    return list(nearest["bid"]), used_same_position


def bid_guidance(candidate_adj_value: float, candidate_position: str, sample: pd.DataFrame) -> dict[str, Any] | None:
    """Real comparable historical bids for a free-agent candidate, plus a
    low/median/high computed directly from that same list - never an
    independently invented number.

    `None` if fewer than `MIN_COMPARABLE_SAMPLE` comparables were found -
    too thin to say anything useful yet (matches this project's existing
    small-sample-guard pattern, e.g. `_sane_ratio`/`QUALIFYING_VOLUME`): an
    honest gap, not a fabricated figure from too few real data points.
    `low`/`high` are the min/max of the comparable set itself, not a
    percentile calculation - a percentile implies more statistical rigor
    than a sample this small (3-5 points) actually supports.
    """
    bids, same_position = nearest_comparable_bids(candidate_adj_value, candidate_position, sample)
    if len(bids) < MIN_COMPARABLE_SAMPLE:
        return None
    sorted_bids = sorted(bids)
    return {
        "comparable_bids": sorted_bids,
        "low": min(sorted_bids),
        "median": statistics.median(sorted_bids),
        "high": max(sorted_bids),
        "same_position": same_position,
    }
