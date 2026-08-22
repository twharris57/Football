"""Player pool selection and FantasyCalc value/multiplier resolution."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pandas as pd

from .constants import FANTASY_POSITIONS

# Position-level correction for FantasyCalc's known scoring mismatch (see
# PROJECT_PLAN_DYNASTY.md): FantasyCalc's values assume 4pt passing TDs and no TE
# premium, not this league's real 6pt passing TDs / +0.5-per-reception TE
# premium. Computed as the ratio of total fantasy points, under this
# league's real rule vs FantasyCalc's assumed baseline rule, holding every
# other scoring setting constant, for startable-volume players (QB: >=200
# attempts; TE: >=30 targets), pooled across the 3 most recent complete
# NFL seasons (2022-2024 as of this derivation — see
# recent_complete_seasons_weekly_data()) rather than a single season, to
# reduce single-season noise (108 qualifying QB player-seasons, 135 TE,
# vs. 39/45 from 2024 alone). Re-derive with
# `python scripts/derive_position_multipliers.py` whenever a fresher
# season becomes available — that script uses the same lookback-from-
# current-season logic, so it doesn't need editing to stay current, only
# re-running (see PROJECT_PLAN_DYNASTY.md for the longer-term plan to automate
# this fully). This corrects only the two largest, most clearly
# attributable gaps — it does NOT correct for the smaller long-TD/first-down
# bonus gaps also noted in PROJECT_PLAN_DYNASTY.md. A real per-player recompute
# (see PROJECT_PLAN_DYNASTY.md's Active valuation work) would replace this; this is
# the deliberately lightweight version.
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
    """Return every fantasy-relevant player on a real NFL roster, regardless of fantasy-roster status.

    The broader population `free_agent_pool` narrows down further (to just
    the non-rostered subset) - shared here so a caller that needs to track
    a player's real NFL-team/depth-chart/status history (`pickup_snapshots.py`)
    can do so across the *whole* population, not just whoever happens to be
    a free agent this refresh. That distinction matters: if history were
    only tracked for the free-agent subset, a player re-entering it via a
    fantasy-roster drop (not an NFL-team change) would look identical to a
    real first-time signing - see `.claude/conventions/valuation_principles.md`'s
    "first time seen in this narrower pool" rule. `team` must be truthy (on
    an actual NFL roster) since Sleeper's player dataset also carries
    retired/practice-squad-only/no-team entries that would otherwise flood
    the pool with irrelevant results.
    """
    return {
        player_id: info
        for player_id, info in players.items()
        if info.get("position") in FANTASY_POSITIONS and info.get("team")
    }


def free_agent_pool(
    players: dict[str, dict], rosters: list[dict], draft_eligible_rookie_ids: frozenset[str] = frozenset()
) -> dict[str, dict]:
    """Return every fantasy-relevant player on a real NFL roster who isn't on any fantasy roster.

    Sleeper has no dedicated "free agents" endpoint - this is the same
    approach `rookie_pool` uses, generalized to every player, not just this
    year's class. `draft_eligible_rookie_ids` (`gather_state`'s own
    undrafted-rookie pool, `frozenset()` once the draft is complete)
    excludes this year's not-yet-drafted class while the startup draft is
    still active - an undrafted rookie mid-draft is a draft prospect, not a
    waiver-wire pickup, even though they aren't in `rostered_player_ids`
    either. Once the draft ends, any still-undrafted rookie is a real free
    agent again and this exclusion naturally stops applying (the caller
    passes an empty set).
    """
    rostered = rostered_player_ids(rosters)
    return {
        player_id: info
        for player_id, info in fantasy_relevant_teamed_players(players).items()
        if player_id not in rostered and player_id not in draft_eligible_rookie_ids
    }


def roster_fantasy_players(roster: dict, players: dict[str, dict]) -> Iterator[tuple[str, dict]]:
    """Yield (player_id, info) for each of the roster's players at a fantasy-relevant position.

    The shared first step of every roster-analysis function below — what
    counts as "fantasy-relevant" (FANTASY_POSITIONS) is defined once here
    instead of re-checked in each one.
    """
    for player_id in roster.get("players") or []:
        info = players.get(player_id, {})
        if info.get("position") in FANTASY_POSITIONS:
            yield player_id, info


def _resolve_multiplier(sleeper_id: str, position: str, multipliers: dict[str, Any]) -> float:
    """Resolve this player's real-scoring multiplier via the fallback chain:
    per-player ratio → rookie play-style-bucket average → flat position
    average → hardcoded `POSITION_VALUE_MULTIPLIER`. See
    docs/rookie-draft-big-board.md's "Valuation" section for the full
    methodology.
    """
    per_player = multipliers.get("per_player", {})
    rookie_bucket = multipliers.get("rookie_bucket", {})
    position_average = multipliers.get("position_average", {})
    if sleeper_id in per_player:
        return per_player[sleeper_id]
    if sleeper_id in rookie_bucket:
        return rookie_bucket[sleeper_id]
    return position_average.get(position, POSITION_VALUE_MULTIPLIER.get(position, 1.0))


def fc_value_by_sleeper_id(fc_values: list[dict], multipliers: dict[str, Any] | None = None) -> dict[str, dict]:
    """Build a sleeperId -> FantasyCalc entry lookup once, for reuse across many calls.

    The marginal-value ranking below calls into value-lookup logic thousands
    of times per refresh (every candidate x every week, across rounds) -
    rebuilding this ~475-entry dict on each of those calls would be wasteful.
    Each entry gets its real-scoring-corrected `adj_value` precomputed here
    (see `_resolve_multiplier`/player_scoring.py) so every downstream caller,
    which already threads this dict through, gets it for free.
    """
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
    """Rank the rookie class by dynasty value into tiers, for display.

    `rookie_pool_` is the whole class (see `rookie_pool`), not just
    undrafted players — a drafted player stays on the board, annotated via
    `draft_attribution` (player_id -> (round, team_name)), rather than
    disappearing. `rank` is value order across the whole class; use
    `drafted_round`/`drafted_by` (both empty if undrafted) to see what's
    actually still available. `value` is FantasyCalc's raw number;
    `adj_value` (real-scoring corrected, see docs/rookie-draft-big-board.md's
    "Valuation" section) determines sort order and `rank`. `tier` is
    FantasyCalc's own global tier across all dynasty-relevant players, not
    rookie-specific or adjusted. `fits_need` flags a current roster need
    (`roster_needs_summary`); `handcuff_to` names the roster's own RB
    starter this rookie would handcuff (`handcuff_map`).
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
