"""Round-by-round rookie draft recommendation plan."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .byes import gap_delta
from .draft_snapshots import AMBIGUOUS
from .lineup import assign_starters, player_value_rows
from .marginal_value import rank_by_marginal_value
from .picks import DraftPickSlot, own_draft_picks
from .roster_needs import need_positions, roster_needs_summary

MAX_DISPLAYED_ALTERNATES = 2


def hypothetical_needs_and_handcuffs(
    player_ids: list[str], players: dict[str, dict], handcuffs: dict[str, str]
) -> tuple[frozenset[str], dict[str, str]]:
    """Recompute need_positions and handcuff targets for a hypothetical (simulated) roster."""
    needs = need_positions(roster_needs_summary({"players": player_ids}, players))
    rb_ids = {pid for pid in player_ids if players.get(pid, {}).get("position") == "RB"}
    handcuff_targets = {
        backup_id: players.get(starter_id, {}).get("full_name", "")
        for starter_id, backup_id in handcuffs.items()
        if starter_id in rb_ids
    }
    return needs, handcuff_targets


def alternate_gap_note(
    candidate_id: str,
    drop: dict | None,
    hypothetical_ids: list[str],
    players: dict[str, dict],
    byes: dict[str, int],
    league: dict,
) -> str:
    """Describe what picking this specific alternate would change about weekly gaps, if anything.

    Compares against the hypothetical roster as it stood entering this
    round (not the plan's final roster), so the note reflects what THIS
    choice specifically does. Structured as a plain string so more note
    types (e.g. injury history, once/if that data is available) can be
    appended later without changing callers.
    """
    with_candidate = hypothetical_ids + [candidate_id]
    roster_after = [pid for pid in with_candidate if drop is None or pid != drop["player_id"]]
    worsened = gap_delta({"players": hypothetical_ids}, {"players": roster_after}, players, byes, league)
    if worsened.empty:
        return ""
    weeks = ", ".join(str(w) for w in worsened["week"])
    return f"would open a gap in week(s) {weeks}"


def multi_round_plan(
    ownership: list[DraftPickSlot],
    user_roster_id: int,
    current_pick_no: int,
    available: dict[str, dict],
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    user_roster: dict,
    league: dict,
    byes: dict[str, int],
    handcuffs: dict[str, str],
    real_picks_by_overall: dict[int, str],
    draft_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Plan for every pick the user owns this draft — what to pick and drop, and why.

    Ranks candidates by season-average marginal starting-lineup value
    (`rank_by_marginal_value`), not raw trade value. Rounds already played
    (`overall_pick < current_pick_no`) show the real player Sleeper
    recorded, scored the same way retroactively rather than a stale
    recommendation. Each completed round's drop is labeled with one of four
    `drop_status` values, from `draft_snapshot` (see draft_snapshots.py's
    `_reconcile` for the mechanics): `"confirmed"` (a real drop, recovered
    by diffing the roster across refreshes), `"confirmed_none"` (confirmed
    no drop was needed - roster had room), `"ambiguous"` (two or more of the
    user's own picks completed in the same refresh gap, so which drop paired
    with which pick can't be isolated), or `"guessed"` (the frontier hasn't
    reached this pick yet, or it's an upcoming round - the same cheap
    heuristic guess as before). Once a pick's real post-drop roster is known
    (`draft_snapshot["confirmed_through_pick"]`), later rounds simulate
    forward from that real state instead of a chain of guesses, bounding
    simulation drift to only the unconfirmed tail of the plan.

    Returns up to `MAX_DISPLAYED_ALTERNATES` backup alternates per upcoming
    round (`alternates_by_pick`, keyed by `overall_pick`), each noting
    whether picking it instead would open a weekly gap the primary pick
    doesn't. `all_candidates_by_pick` (same keys) holds every candidate
    evaluated for that round, not just the displayed few — free to expose
    since `rank_by_marginal_value` already scores all of them; its
    `drop_name`/`drop_is_starter` come from the same cheap heuristic as the
    ranking, not a per-candidate optimal search (a UI wanting that should
    call `best_position_relevant_drop()` with `hypothetical_ids_by_pick`'s
    snapshot for that round instead). Finally compares the resulting
    hypothetical roster's weekly gaps against the current roster's,
    flagging any week the full plan would newly break. Full rationale in
    docs/rookie-draft-big-board.md's "Draft plan" section.
    """
    own_picks = own_draft_picks(ownership, user_roster_id)

    available_ids = set(available.keys())
    hypothetical_ids = list(user_roster.get("players") or [])
    # The roster's current taxi/IR players are never eligible for a starting
    # slot in the simulation below - Sleeper doesn't allow it - regardless
    # of how their value compares to the rest of the roster.
    ineligible_ids = frozenset(user_roster.get("taxi") or []) | frozenset(user_roster.get("reserve") or [])
    # A drafted rookie can never actually be assigned to reserve/IR (that
    # requires a real injury designation) - only the roster's *actual*
    # current IR headcount should count toward total capacity, not the
    # league's full reserve_slots setting (see roster_total_capacity).
    # Reserve occupancy doesn't change across simulated rounds, since no
    # simulated pick ever lands on it, so this is computed once.
    reserve_filled = len(user_roster.get("reserve") or [])
    just_picked: set[str] = set()

    rounds = []
    alternates_by_pick: dict[int, pd.DataFrame] = {}
    all_candidates_by_pick: dict[int, pd.DataFrame] = {}
    hypothetical_ids_by_pick: dict[int, list[str]] = {}

    for pick in own_picks:
        is_completed = pick.overall_pick < current_pick_no
        real_pick_id = real_picks_by_overall.get(pick.overall_pick)
        needs, handcuff_targets = hypothetical_needs_and_handcuffs(hypothetical_ids, players, handcuffs)
        # Snapshot the roster as it stands entering this round, so a UI can
        # later look up best_position_relevant_drop() on demand for any
        # candidate from this specific round's context, not just whichever
        # one this loop happens to pick.
        hypothetical_ids_by_pick[pick.overall_pick] = list(hypothetical_ids)

        if is_completed and real_pick_id:
            candidate_ids, top_n = [real_pick_id], 1
        else:
            # rank_by_marginal_value already evaluates every candidate before
            # sorting/slicing - asking for all of them here costs nothing
            # extra (see its docstring's ~20,000-call performance note,
            # which already assumes every candidate is scored every round).
            # This lets the UI offer a full player-projection lookup, not
            # just the top few, for free.
            candidate_ids, top_n = list(available_ids), len(available_ids)

        ranked = rank_by_marginal_value(
            candidate_ids,
            hypothetical_ids,
            players,
            fc_by_sleeper_id,
            byes,
            league,
            top_n=top_n,
            exclude_from_drop=frozenset(just_picked),
            ineligible_ids=ineligible_ids,
            reserve_filled=reserve_filled,
        )
        if not ranked:
            break

        primary = ranked[0]
        picked_id = primary["player_id"]
        drop = primary["drop"]
        picked_info = players.get(picked_id, {})

        # Override the heuristic guess with real, recovered drop data when
        # available (see draft_snapshots.py) - a completed round's key is
        # only present once its gap has actually been reconciled.
        confirmed_key = str(pick.overall_pick)
        if is_completed and confirmed_key in draft_snapshot["confirmed_drops"]:
            confirmed_entry = draft_snapshot["confirmed_drops"][confirmed_key]
            if confirmed_entry == AMBIGUOUS:
                drop_status = "ambiguous"
                # keep the heuristic `drop` as the displayed (uncertain) guess
            elif confirmed_entry is None:
                drop_status, drop = "confirmed_none", None
            else:
                drop_status = "confirmed"
                drop_info = players.get(confirmed_entry, {})
                # is_starter: was this player a starter in the roster as it
                # stood entering this round (hypothetical_ids, still
                # accurate at this point in the loop)?
                pre_round_rows = player_value_rows(hypothetical_ids, players, fc_by_sleeper_id)
                pre_round_starters = {
                    pid for _, pid in assign_starters(pre_round_rows, league["roster_positions"]) if pid
                }
                drop = {
                    "player_id": confirmed_entry,
                    "name": drop_info.get("full_name"),
                    "pos": drop_info.get("position"),
                    "is_starter": confirmed_entry in pre_round_starters,
                }
        else:
            drop_status = "guessed"

        if is_completed and real_pick_id:
            reason = "already picked"
        else:
            reasons = [f"adds {primary['marginal_value']:+.0f} to season-average starting value (bye-adjusted)"]
            if picked_info.get("position") in needs:
                reasons.append(f"also a flagged need at {picked_info.get('position')}")
            handcuff_to = handcuff_targets.get(picked_id)
            if handcuff_to:
                reasons.append(f"also handcuffs your own {handcuff_to}")
            reason = "; ".join(reasons)

        rounds.append(
            {
                "round": pick.round,
                "overall_pick": pick.overall_pick,
                "status": "completed" if is_completed else "upcoming",
                "pick_name": picked_info.get("full_name"),
                "pick_pos": picked_info.get("position"),
                "marginal_value": round(primary["marginal_value"], 1),
                "reason": reason,
                "drop_name": drop["name"] if drop else None,
                "drop_pos": drop["pos"] if drop else None,
                "drop_is_starter": drop["is_starter"] if drop else None,
                "drop_status": drop_status,
            }
        )

        if len(ranked) > 1:
            alt_rows = []
            for alt in ranked[1:MAX_DISPLAYED_ALTERNATES + 1]:
                alt_info = players.get(alt["player_id"], {})
                alt_drop = alt["drop"]
                alt_rows.append(
                    {
                        "name": alt_info.get("full_name"),
                        "pos": alt_info.get("position"),
                        "marginal_value": round(alt["marginal_value"], 1),
                        "drop_name": alt_drop["name"] if alt_drop else None,
                        "drop_is_starter": alt_drop["is_starter"] if alt_drop else None,
                        "notes": alternate_gap_note(
                            alt["player_id"], alt_drop, hypothetical_ids, players, byes, league
                        ),
                    }
                )
            alternates_by_pick[pick.overall_pick] = pd.DataFrame(alt_rows)

            # Every other evaluated candidate, for on-demand lookup (a
            # dropdown in the web UI) rather than the fixed top few above -
            # no extra scoring cost, since rank_by_marginal_value already
            # evaluates all of them before sorting (see the top_n comment
            # above). Deliberately omits alternate_gap_note - fine for a
            # couple of backups above, but a per-candidate weekly-gap
            # comparison for the whole ~200-player pool isn't worth the cost
            # for a lookup table most entries in which nobody will ever open.
            candidate_rows = []
            for candidate in ranked:
                info = players.get(candidate["player_id"], {})
                candidate_drop = candidate["drop"]
                candidate_rows.append(
                    {
                        "player_id": candidate["player_id"],
                        "name": info.get("full_name"),
                        "pos": info.get("position"),
                        "marginal_value": round(candidate["marginal_value"], 1),
                        "drop_name": candidate_drop["name"] if candidate_drop else None,
                        "drop_is_starter": candidate_drop["is_starter"] if candidate_drop else None,
                    }
                )
            all_candidates_by_pick[pick.overall_pick] = pd.DataFrame(candidate_rows)

        available_ids.discard(picked_id)
        if pick.overall_pick == draft_snapshot["confirmed_through_pick"]:
            # The real post-drop roster is now known for every pick up
            # through this one - jump straight to it instead of carrying
            # forward a chain of guesses (including any "ambiguous" ones),
            # so simulation drift never extends past the unconfirmed tail.
            hypothetical_ids = list(draft_snapshot["confirmed_roster"])
        else:
            if drop:
                hypothetical_ids = [pid for pid in hypothetical_ids if pid != drop["player_id"]]
            hypothetical_ids.append(picked_id)
        just_picked.add(picked_id)

    hypothetical_roster = {"players": hypothetical_ids}
    alerts = gap_delta(user_roster, hypothetical_roster, players, byes, league)

    return {
        "rounds": pd.DataFrame(rounds),
        "alternates_by_pick": alternates_by_pick,
        "all_candidates_by_pick": all_candidates_by_pick,
        "hypothetical_ids_by_pick": hypothetical_ids_by_pick,
        "weekly_gap_alerts": alerts.reset_index(drop=True),
    }
