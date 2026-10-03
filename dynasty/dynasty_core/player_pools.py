"""Player pool selection and FantasyCalc value/multiplier resolution."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pandas as pd

from .constants import FANTASY_POSITIONS

# Last-resort fallback for player_scoring's per-player correction: the points ratio
# (league scoring vs. FantasyCalc's baseline) for 6pt passing TDs and TE premium only,
# pooled over 2022-24. Re-derive with scripts/derive_position_multipliers.py.
POSITION_VALUE_MULTIPLIER = {
    "QB": 1.175,
    "TE": 1.202,
}


def rostered_player_ids(rosters: list[dict]) -> set[str]:
    """Return every player_id currently on any team's roster."""
    ids: set[str] = set()
    for roster in rosters:
        ids.update(roster.get("players") or [])
    return ids


def rookie_pool(players: dict[str, dict], season: str) -> dict[str, dict]:
    """Return this season's rookie class at fantasy-relevant positions."""
    return {
        player_id: info
        for player_id, info in players.items()
        if info.get("position") in FANTASY_POSITIONS
        and (info.get("metadata") or {}).get("rookie_year") == season
    }


def fantasy_relevant_teamed_players(players: dict[str, dict]) -> dict[str, dict]:
    """Every fantasy-position player on an NFL team, rostered or not.

    Pickup history tracks this whole population, so a fantasy drop isn't mistaken for
    a real signing.
    """
    return {
        player_id: info
        for player_id, info in players.items()
        if info.get("position") in FANTASY_POSITIONS and info.get("team")
    }


def free_agent_pool(
    players: dict[str, dict], rosters: list[dict], draft_eligible_rookie_ids: frozenset[str] = frozenset()
) -> dict[str, dict]:
    """Fantasy-position players on NFL teams who aren't on any fantasy roster.

    `draft_eligible_rookie_ids` excludes undrafted rookies while the draft is live.
    """
    rostered = rostered_player_ids(rosters)
    return {
        player_id: info
        for player_id, info in fantasy_relevant_teamed_players(players).items()
        if player_id not in rostered and player_id not in draft_eligible_rookie_ids
    }


def roster_fantasy_players(roster: dict, players: dict[str, dict]) -> Iterator[tuple[str, dict]]:
    """Yield `(player_id, info)` for the roster's players at fantasy positions."""
    for player_id in roster.get("players") or []:
        info = players.get(player_id, {})
        if info.get("position") in FANTASY_POSITIONS:
            yield player_id, info


def _resolve_multiplier(sleeper_id: str, position: str, multipliers: dict[str, Any]) -> float:
    """Real-scoring multiplier: own ratio, else rookie bucket, else position average, else constant."""
    per_player = multipliers.get("per_player", {})
    rookie_bucket = multipliers.get("rookie_bucket", {})
    position_average = multipliers.get("position_average", {})
    if sleeper_id in per_player:
        return per_player[sleeper_id]
    if sleeper_id in rookie_bucket:
        return rookie_bucket[sleeper_id]
    return position_average.get(position, POSITION_VALUE_MULTIPLIER.get(position, 1.0))


def fc_value_by_sleeper_id(fc_values: list[dict], multipliers: dict[str, Any] | None = None) -> dict[str, dict]:
    """sleeperId -> FantasyCalc entry with `adj_value` precomputed. Build once per refresh."""
    multipliers = multipliers or {}
    result: dict[str, dict] = {}
    for entry in fc_values:
        sleeper_id = entry["player"].get("sleeperId")
        if not sleeper_id:
            continue
        position = entry["player"].get("position")
        value = entry.get("value")
        multiplier = _resolve_multiplier(sleeper_id, position, multipliers)
        result[sleeper_id] = {**entry, "adj_value": value * multiplier if value is not None else None}
    return result


def build_big_board(
    rookie_pool_: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    need_positions: frozenset[str] = frozenset(),
    handcuff_targets: dict[str, str] | None = None,
    draft_attribution: dict[str, tuple[int, str]] | None = None,
) -> pd.DataFrame:
    """Rank the whole rookie class by `adj_value` into tiers.

    Drafted players stay, with `drafted_round`/`drafted_by`. `tier` is FantasyCalc's
    global tier. `fits_need` and `handcuff_to` are relative to the user's roster.
    """
    handcuff_targets = handcuff_targets or {}
    draft_attribution = draft_attribution or {}

    rows = []
    for player_id, info in rookie_pool_.items():
        fc_entry = fc_by_sleeper_id.get(player_id)
        position = info.get("position")
        value = fc_entry["value"] if fc_entry else None
        drafted_round, drafted_by = draft_attribution.get(player_id, (None, ""))
        rows.append(
            {
                "name": info.get("full_name"),
                "pos": position,
                "fits_need": position in need_positions,
                "handcuff_to": handcuff_targets.get(player_id, ""),
                "drafted_round": drafted_round,
                "drafted_by": drafted_by,
                "team": info.get("team") or "FA",
                "college": info.get("college"),
                "age": info.get("age"),
                "value": value,
                "adj_value": fc_entry.get("adj_value") if fc_entry else None,
                "tier": fc_entry.get("maybeTier") if fc_entry else None,
            }
        )

    board = pd.DataFrame(rows)
    if board.empty:
        return board

    board["drafted_round"] = board["drafted_round"].astype("Int64")
    board = board.sort_values("adj_value", ascending=False, na_position="last").reset_index(drop=True)
    unranked_tier = int(board["tier"].max() + 1) if board["tier"].notna().any() else 1
    board["tier"] = board["tier"].fillna(unranked_tier).astype(int)
    board.insert(0, "rank", board.index + 1)
    return board
