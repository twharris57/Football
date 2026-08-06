"""Draft pick ownership and trade-value-of-picks."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class DraftPickSlot:
    """One pick in the rookie draft: its overall slot and current owner."""

    round: int
    overall_pick: int
    original_roster_id: int
    owner_roster_id: int


def resolve_user_roster_id(users: list[dict], rosters: list[dict], username: str) -> int:
    """Return the roster_id owned by the given Sleeper username."""
    user = next((u for u in users if u["display_name"].lower() == username.lower()), None)
    if user is None:
        raise ValueError(f"No user named {username!r} found in this league")
    roster = next(r for r in rosters if r["owner_id"] == user["user_id"])
    return roster["roster_id"]


def team_name_by_roster_id(rosters: list[dict], users: list[dict]) -> dict[int, str]:
    """Map roster_id to a display name: team name plus the owner's Sleeper
    username in parentheses when both exist (e.g. "My Epic Team Name
    (bob)") - knowing which real person is on the other end of a trade
    matters, not just their team's display name. Falls back to just the
    username, or a synthetic "Roster N" label, when there's no set team
    name or no matched user at all - never username duplicated in both
    slots.
    """
    user_by_id = {u["user_id"]: u for u in users}
    names = {}
    for roster in rosters:
        user = user_by_id.get(roster["owner_id"])
        team_name = (user.get("metadata") or {}).get("team_name") if user else None
        username = (user or {}).get("display_name")
        if team_name and username:
            names[roster["roster_id"]] = f"{team_name} ({username})"
        else:
            names[roster["roster_id"]] = team_name or username or f"Roster {roster['roster_id']}"
    return names


def compute_pick_ownership(draft: dict, traded_picks: list[dict], season: str) -> list[DraftPickSlot]:
    """Return every pick in this draft, in overall-pick order, with trades applied.

    Assumes a "linear" draft (same slot-to-roster order every round) -
    this league's actual, confirmed draft type. The overall-pick math below
    would silently compute wrong pick ownership under a snake draft (which
    reverses slot order on even rounds) - not implemented, since it's never
    been needed - so this fails loudly instead if that ever changes.
    """
    if draft.get("type") != "linear":
        raise ValueError(
            f"compute_pick_ownership only supports a 'linear' draft type, got {draft.get('type')!r} - "
            "pick ownership math assumes the same slot order every round, which a snake or auction "
            "draft would violate."
        )
    num_teams = draft["settings"]["teams"]
    rounds = draft["settings"]["rounds"]
    slot_to_roster = {int(slot): roster_id for slot, roster_id in draft["slot_to_roster_id"].items()}

    traded_owner_by_round_and_roster = {
        (t["round"], t["roster_id"]): t["owner_id"] for t in traded_picks if t["season"] == season
    }

    picks = []
    for round_num in range(1, rounds + 1):
        for slot in range(1, num_teams + 1):
            original_roster_id = slot_to_roster[slot]
            overall_pick = (round_num - 1) * num_teams + slot
            owner_roster_id = traded_owner_by_round_and_roster.get(
                (round_num, original_roster_id), original_roster_id
            )
            picks.append(DraftPickSlot(round_num, overall_pick, original_roster_id, owner_roster_id))
    return picks


# FantasyCalc's ordinal round names (see pick_trade_values) only ever go to
# 4th - this league's actual round count, confirmed via its own pick-value
# buckets. A round beyond that falls back to a plain f"{n}th", a real but
# untested edge case (this league has never had a 5+ round rookie draft).
ROUND_ORDINAL = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}

# How many seasons past the current one to project pick ownership/value for.
# Sleeper's traded_picks endpoint has no fixed "how many years out" window -
# it only ever contains entries for picks that have actually been traded, so
# there's no real signal for "these are all the picks that will ever exist."
# Capped at 1 (next season only): further out, `_future_pick_owners`'s
# real-unless-traded assumption is on shakier ground the longer nothing's
# actually been traded there, and it would list picks with zero real trade
# activity - clutter, not real decision value. A deliberate scope limit, not
# a data gap to try to solve exactly.
FUTURE_PICK_YEARS_AHEAD = 1


def _future_pick_owners(
    num_teams: int, num_rounds: int, traded_picks: list[dict], season: str
) -> list[tuple[int, int, int]]:
    """Every (round, original_roster_id, current_owner_roster_id) for a season with no real draft object yet.

    Unlike `compute_pick_ownership`, there's no Sleeper draft/slot_to_roster
    to pull a real slot order from for a season that hasn't happened - every
    roster owns its own pick each round unless `traded_picks` says otherwise.
    """
    traded_owner = {(t["round"], t["roster_id"]): t["owner_id"] for t in traded_picks if t["season"] == season}
    return [
        (round_num, roster_id, traded_owner.get((round_num, roster_id), roster_id))
        for round_num in range(1, num_rounds + 1)
        for roster_id in range(1, num_teams + 1)
    ]


def pick_trade_values(
    ownership: list[DraftPickSlot],
    current_pick_no: int,
    traded_picks: list[dict],
    num_teams: int,
    num_rounds: int,
    season: str,
    fc_values: list[dict],
    team_names: dict[int, str],
) -> pd.DataFrame:
    """Every remaining/near-future rookie-draft pick, valued and matched to its real current owner.

    Uses FantasyCalc's raw pick `value`, not `adj_value` (a pick has no
    statistical production for the real-scoring correction to apply to).
    Matched by FantasyCalc's own pick-name string (e.g. "2026 Pick 1.01",
    "2027 1st") — a naming-convention change on their end wouldn't raise,
    just leave `value` empty for everything, so an all-empty `value` column
    is worth a spot-check against FantasyCalc's actual pick names. See
    docs/rookie-draft-big-board.md's "Trade targets & sells" section for the
    full methodology (why this season vs. next season are valued
    differently, and why seasons beyond that aren't included).
    """
    pick_value_by_name = {
        entry["player"]["name"]: entry["value"] for entry in fc_values if entry["player"].get("position") == "PICK"
    }

    rows = []
    for pick in ownership:
        if pick.overall_pick < current_pick_no:
            continue
        slot = pick.overall_pick - (pick.round - 1) * num_teams
        name = f"{season} Pick {pick.round}.{slot:02d}"
        rows.append(
            {
                "pick": name,
                "owner": team_names.get(pick.owner_roster_id, "Unknown"),
                "owner_roster_id": pick.owner_roster_id,
                "value": pick_value_by_name.get(name),
            }
        )

    future_season = str(int(season) + FUTURE_PICK_YEARS_AHEAD)
    for round_num, _original_roster_id, owner_roster_id in _future_pick_owners(
        num_teams, num_rounds, traded_picks, future_season
    ):
        name = f"{future_season} {ROUND_ORDINAL.get(round_num, f'{round_num}th')}"
        rows.append(
            {
                "pick": name,
                "owner": team_names.get(owner_roster_id, "Unknown"),
                "owner_roster_id": owner_roster_id,
                "value": pick_value_by_name.get(name),
            }
        )

    return pd.DataFrame(rows).sort_values("value", ascending=False, na_position="last").reset_index(drop=True)


def picks_until_turn(ownership: list[DraftPickSlot], user_roster_id: int, current_pick_no: int) -> int | None:
    """Return how many picks (by anyone) happen before the user's next pick.

    0 means it's the user's turn right now. None means the user has no
    more picks left in this draft.
    """
    next_pick = next(
        (p for p in ownership if p.owner_roster_id == user_roster_id and p.overall_pick >= current_pick_no),
        None,
    )
    return next_pick.overall_pick - current_pick_no if next_pick else None


def format_your_picks(
    ownership: list[DraftPickSlot], user_roster_id: int, current_pick_no: int, team_names: dict[int, str]
) -> pd.DataFrame:
    """Return every pick the user owns in this draft, made or upcoming."""
    rows = []
    for pick in ownership:
        if pick.owner_roster_id != user_roster_id:
            continue
        acquired_from = (
            team_names.get(pick.original_roster_id) if pick.original_roster_id != pick.owner_roster_id else None
        )
        rows.append(
            {
                "round": pick.round,
                "overall_pick": pick.overall_pick,
                "status": "made" if pick.overall_pick < current_pick_no else "upcoming",
                "acquired_from": acquired_from,
            }
        )
    return pd.DataFrame(rows)
