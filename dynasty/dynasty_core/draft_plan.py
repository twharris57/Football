"""Round-by-round rookie draft recommendation plan."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .byes import gap_delta
from .draft_snapshots import AMBIGUOUS
from .handcuffs import handcuff_targets as handcuff_targets_for
from .lineup import assign_starters, player_value_rows
from .marginal_value import rank_by_marginal_value
from .picks import DraftPickSlot, own_draft_picks
from .roster_needs import phase_aware_need_positions

MAX_DISPLAYED_ALTERNATES = 2


def hypothetical_needs_and_handcuffs(
    player_ids: list[str],
    players: dict[str, dict],
    handcuffs: dict[str, str],
    fc_by_sleeper_id: dict[str, dict],
    replacement_level: dict[str, float],
    roster_positions: list[str],
    phase: str,
) -> tuple[frozenset[str], dict[str, str]]:
    """Phase-aware need positions and handcuff targets for a simulated roster."""
    needs = phase_aware_need_positions(
        {"players": player_ids}, players, fc_by_sleeper_id, replacement_level, roster_positions, phase
    )
    return needs, handcuff_targets_for(player_ids, players, handcuffs)


def alternate_gap_note(
    candidate_id: str,
    drop: dict | None,
    hypothetical_ids: list[str],
    players: dict[str, dict],
    byes: dict[str, int],
    league: dict,
) -> str:
    """How picking this alternate changes weekly gaps versus the roster entering the round."""
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
    replacement_level: dict[str, float] | None = None,
    phase: str = "rebuilding",
) -> dict[str, Any]:
    """What to pick and drop with each of the user's picks this draft.

    - Ranks by marginal lineup value.
    - Completed rounds show the real pick, with `drop_status` from `draft_snapshot`:
      confirmed, confirmed_none, ambiguous, or guessed.
    - Later rounds simulate from the last confirmed roster.
    - Returns up to `MAX_DISPLAYED_ALTERNATES` alternates per round, every scored candidate
      (`all_candidates_by_pick`, heuristic drops), each round's starting roster
      (`hypothetical_ids_by_pick`), and weekly gaps the plan would open.
    """
    own_picks = own_draft_picks(ownership, user_roster_id)
    replacement_level = replacement_level or {}

    available_ids = set(available.keys())
    hypothetical_ids = list(user_roster.get("players") or [])
    ineligible_ids = frozenset(user_roster.get("taxi") or []) | frozenset(user_roster.get("reserve") or [])
    # Only currently occupied IR slots count; simulated picks never land on IR.
    reserve_filled = len(user_roster.get("reserve") or [])
    just_picked: set[str] = set()

    rounds = []
    alternates_by_pick: dict[int, pd.DataFrame] = {}
    all_candidates_by_pick: dict[int, pd.DataFrame] = {}
    hypothetical_ids_by_pick: dict[int, list[str]] = {}

    for pick in own_picks:
        is_completed = pick.overall_pick < current_pick_no
        real_pick_id = real_picks_by_overall.get(pick.overall_pick)
        needs, handcuff_targets = hypothetical_needs_and_handcuffs(
            hypothetical_ids, players, handcuffs, fc_by_sleeper_id, replacement_level, league["roster_positions"], phase
        )
        # Kept so the UI can run best_position_relevant_drop() for any candidate this round.
        hypothetical_ids_by_pick[pick.overall_pick] = list(hypothetical_ids)

        if is_completed and real_pick_id:
            candidate_ids, top_n = [real_pick_id], 1
        else:
            # Free: rank_by_marginal_value already scores every candidate.
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

        # Replace the heuristic drop with the recovered one once this pick is reconciled.
        confirmed_key = str(pick.overall_pick)
        if is_completed and confirmed_key in draft_snapshot["confirmed_drops"]:
            confirmed_entry = draft_snapshot["confirmed_drops"][confirmed_key]
            if confirmed_entry == AMBIGUOUS:
                drop_status = "ambiguous"
                # keep the heuristic drop as the displayed guess
            elif confirmed_entry is None:
                drop_status, drop = "confirmed_none", None
            else:
                drop_status = "confirmed"
                drop_info = players.get(confirmed_entry, {})
                # Was the dropped player starting entering this round? Taxi/IR can't start.
                pre_round_rows = player_value_rows(hypothetical_ids, players, fc_by_sleeper_id)
                pre_round_eligible_rows = [r for r in pre_round_rows if r["player_id"] not in ineligible_ids]
                pre_round_starters = {
                    pid for _, pid in assign_starters(pre_round_eligible_rows, league["roster_positions"]) if pid
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

            # Every other candidate, for the UI lookup. No gap note: too costly for ~200 rows.
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
            # Continue from the real post-drop roster rather than a chain of guesses.
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
