"""Top-level orchestrator: pull one full league/draft snapshot and compute everything derived from it."""

from __future__ import annotations

import logging
from typing import Any

import fantasycalc_api as fantasycalc
import pandas as pd
import player_scoring
import requests
import sleeper_api as sleeper

from .byes import bye_week_by_team
from .draft_plan import multi_round_plan
from .draft_snapshots import reconcile_snapshot
from .handcuffs import handcuff_map, handcuff_targets
from .picks import (
    compute_pick_ownership,
    format_your_picks,
    own_draft_picks,
    pick_trade_values,
    picks_until_turn,
    resolve_user_roster_id,
    team_name_by_roster_id,
)
from .player_pools import (
    build_big_board,
    fc_value_by_sleeper_id,
    free_agent_pool,
    rookie_pool,
    rostered_player_ids,
)
from .power_timeline import team_power_timeline_scores
from .roster_needs import position_replacement_levels
from .summary import build_attention_digest
from .team_analysis import team_roster_analysis

logger = logging.getLogger(__name__)


def gather_state(
    league_id: str, username: str, force_full_refresh: bool, force_scoring_refresh: bool = False
) -> dict[str, Any]:
    """Pull one full snapshot of league + draft state and compute the big board.

    `force_scoring_refresh` is deliberately its own, separate flag - see the
    comment above the `player_scoring.get_multipliers` call below for why
    `force_full_refresh` alone never triggers it.
    """
    # Named per-service so a connectivity failure tells the user which of
    # the two unauthenticated public APIs actually failed, instead of a
    # single generic "Couldn't reach Sleeper/FantasyCalc" that's true of
    # either - draft day means everyone hits both at once, so this comes up
    # for real, not just in theory.
    try:
        league = sleeper.get_league(league_id)
        rosters = sleeper.get_rosters(league_id)
        users = sleeper.get_users(league_id)
        draft = sleeper.get_draft(league["draft_id"])
        draft_picks = sleeper.get_draft_picks(league["draft_id"])
        traded_picks = sleeper.get_traded_picks(league_id)
        players = sleeper.get_players(force_refresh=force_full_refresh)
    except requests.RequestException as exc:
        raise requests.RequestException(f"Couldn't reach Sleeper: {exc}") from exc

    num_qbs = league["roster_positions"].count("QB") + league["roster_positions"].count("SUPER_FLEX")
    num_teams = league["settings"]["num_teams"]
    ppr = league["scoring_settings"].get("rec", 0)
    try:
        fc_values = fantasycalc.get_dynasty_values(
            num_qbs=num_qbs, num_teams=num_teams, ppr=ppr, force_refresh=force_full_refresh
        )
    except requests.RequestException as exc:
        raise requests.RequestException(f"Couldn't reach FantasyCalc: {exc}") from exc

    # Enrichment from nfl_data_py: optional, must not break the core draft
    # board if the feed is unavailable or its schema drifts (it already has
    # once - the 2026 depth chart columns differ from prior seasons).
    #
    # "Force full refresh" alone never triggers a scoring-multiplier
    # recompute - that pull is a 1-2 minute synchronous re-import of 3
    # seasons of weekly + play-by-play data, for data that's entirely
    # historical and doesn't change mid-draft, and forcing it live risked
    # freezing the app right when the user is on the clock. It's only ever
    # triggered by the separate, explicit `force_scoring_refresh` - the
    # web UI's "Advanced refresh" prewarm option, or
    # `python scripts/derive_position_multipliers.py` run directly.
    # Collected so the UI can surface a real warning instead of a fallback
    # that's silently indistinguishable from "there's nothing to report."
    data_warnings: list[str] = []

    try:
        multipliers = player_scoring.get_multipliers(
            league["scoring_settings"], league["season"], force_refresh=force_scoring_refresh
        )
    except Exception:
        logger.warning("Failed to compute real-scoring multipliers; falling back to position defaults", exc_info=True)
        multipliers = {}
        data_warnings.append(
            "Real-scoring multipliers unavailable this refresh - values are using position-average "
            "or hardcoded fallbacks, not each player's own recomputed ratio."
        )
    fc_by_sleeper_id = fc_value_by_sleeper_id(fc_values, multipliers)

    try:
        byes = bye_week_by_team(league["season"], force_refresh=force_full_refresh)
    except Exception:
        logger.warning("Failed to fetch bye weeks; skipping bye-conflict analysis", exc_info=True)
        byes = {}
        data_warnings.append(
            "Bye week data unavailable this refresh - bye-week impact will show no weeks, which "
            "does not mean there are none."
        )
    try:
        handcuffs = handcuff_map(league["season"], force_refresh=force_full_refresh)
    except Exception:
        logger.warning("Failed to fetch depth charts; skipping handcuff analysis", exc_info=True)
        handcuffs = {}
        data_warnings.append(
            "Handcuff data unavailable this refresh - handcuff flags will show none, which does "
            "not mean there are none."
        )

    user_roster_id = resolve_user_roster_id(users, rosters, username)
    team_names = team_name_by_roster_id(rosters, users)
    user_roster = next(r for r in rosters if r["roster_id"] == user_roster_id)

    user_handcuff_targets = handcuff_targets(user_roster.get("players") or [], players, handcuffs)

    ownership = compute_pick_ownership(draft, traded_picks, league["season"])
    picked_player_ids = {p["player_id"] for p in draft_picks if p.get("player_id")}
    current_pick_no = len(draft_picks) + 1
    # Reuses draft["settings"]["teams"]/["rounds"], not league["settings"]["num_teams"],
    # to decode ownership's overall_pick -> slot the same way compute_pick_ownership
    # encoded it - the two should always agree, but this keeps the encode/decode
    # symmetric even if they ever didn't.
    pick_values = pick_trade_values(
        ownership,
        current_pick_no,
        traded_picks,
        draft["settings"]["teams"],
        draft["settings"]["rounds"],
        league["season"],
        fc_values,
        team_names,
    )
    # pick_trade_values matches picks by FantasyCalc's own name string (its
    # only stable join key for picks) - a naming-convention change on their
    # end wouldn't raise, just leave every value blank, silently
    # indistinguishable from "there's nothing to report" without this.
    if not pick_values.empty and pick_values["value"].isna().all():
        data_warnings.append(
            "Draft pick trade values unavailable this refresh - couldn't match any pick to "
            "FantasyCalc's current pick names, which may mean their naming convention changed."
        )

    unavailable = rostered_player_ids(rosters) | picked_player_ids
    rookies = rookie_pool(players, league["season"])
    available = {pid: info for pid, info in rookies.items() if pid not in unavailable}

    # The board itself shows the whole class, drafted or not (see build_big_board) -
    # only excludes rookies rostered outside this draft entirely (e.g. a pre-draft
    # waiver add), not ones taken here, which stay visible with attribution.
    pre_draft_rostered = rostered_player_ids(rosters) - picked_player_ids
    board_pool = {pid: info for pid, info in rookies.items() if pid not in pre_draft_rostered}
    draft_attribution = {
        p["player_id"]: (p["round"], team_names.get(p["roster_id"]))
        for p in draft_picks
        if p.get("player_id")
    }

    real_picks_by_overall = {
        p["pick_no"]: p["player_id"] for p in draft_picks if p.get("roster_id") == user_roster_id and p.get("player_id")
    }

    # Reconciles the real roster (diffed across refreshes) against what's
    # already recorded for this draft, to recover which drop actually
    # happened for a completed round instead of only ever showing a live
    # guess - see draft_snapshots.py. Independent of force_full_refresh:
    # this isn't market-data freshness, and shouldn't be silently wiped
    # mid-draft by an unrelated refresh flag.
    own_picks = own_draft_picks(ownership, user_roster_id)
    draft_snapshot = reconcile_snapshot(
        league["draft_id"], own_picks, current_pick_no, user_roster.get("players") or [], real_picks_by_overall
    )

    # Undrafted rookies are draft prospects, not waiver-wire pickups, for as
    # long as this startup draft still has picks remaining - excluded from
    # free agents via the same `available` pool already computed above for
    # the draft plan itself, not a second rookie-eligibility computation.
    # Once the draft is done, this is an empty set and they become real
    # free agents again automatically.
    total_draft_picks = draft["settings"]["teams"] * draft["settings"]["rounds"]
    draft_eligible_rookie_ids = frozenset() if current_pick_no > total_draft_picks else frozenset(available.keys())
    available_free_agents = free_agent_pool(players, rosters, draft_eligible_rookie_ids)

    replacement_level = position_replacement_levels(rosters, players, fc_by_sleeper_id, league["roster_positions"])
    user_analysis = team_roster_analysis(
        user_roster, players, fc_by_sleeper_id, byes, league, handcuffs, replacement_level, available_free_agents
    )
    # Cheap for the whole league in one pass (no new API calls, just
    # positional_strength_summary reused per roster) - computed here once
    # rather than on demand per team, unlike team_roster_analysis, since
    # every team's row is needed together for the z-scoring itself.
    power_timeline = team_power_timeline_scores(rosters, players, fc_by_sleeper_id, replacement_level, league)

    recent_rows = []
    for pick in sorted(draft_picks, key=lambda p: p["pick_no"])[-5:]:
        info = players.get(pick["player_id"], {})
        recent_rows.append(
            {
                "pick": pick["pick_no"],
                "team": team_names.get(pick["roster_id"]),
                "player": info.get("full_name"),
                "pos": info.get("position"),
            }
        )

    big_board = build_big_board(
        board_pool, fc_by_sleeper_id, user_analysis["need_positions"], user_handcuff_targets, draft_attribution
    )

    attention_digest = build_attention_digest(
        user_analysis["need_positions"],
        user_analysis["roster_weekly_gaps"],
        user_analysis["sellable_players"],
        user_analysis["free_agent_board"],
        # Same field/fallback roster_tab.py's _render_bye_impact() already
        # uses for "already happened" vs. "still ahead" - not otherwise
        # threaded through gather_state() yet.
        league["settings"].get("leg", 1),
    )

    return {
        "league": league,
        "players": players,
        "fc_by_sleeper_id": fc_by_sleeper_id,
        "byes": byes,
        "handcuffs": handcuffs,
        # League-wide, computed once per refresh regardless of which team's
        # roster is being viewed (see position_replacement_levels) - exposed
        # so the Roster tab's team selector can pass it into an
        # on-demand team_roster_analysis() call for any other team too.
        "replacement_level": replacement_level,
        # Every non-rostered fantasy-relevant player on a real NFL roster
        # (see free_agent_pool) - computed once per refresh, same reuse
        # pattern as replacement_level above, so the team selector's
        # on-demand team_roster_analysis() calls don't each recompute it.
        "available_free_agents": available_free_agents,
        # Informational only - no bid-threshold modeling yet (see
        # .claude/PROJECT_PLAN.md). league["settings"]["waiver_budget"] is
        # this league's total per-team FAAB budget (confirmed FAAB, not
        # priority waivers: waiver_type == 2); waiver_budget_used is each
        # roster's own spend so far, both already pulled with no new fetch.
        "user_faab_remaining": (
            league["settings"].get("waiver_budget", 0) - (user_roster.get("settings") or {}).get("waiver_budget_used", 0)
        ),
        # Every team's continuous power/timeline read, indexed by roster_id
        # (see team_power_timeline_scores) - computed once for the whole
        # league here since z-scoring needs every team's row together, then
        # a UI just looks up the selected team's row rather than
        # recomputing on demand like team_roster_analysis.
        "team_power_timeline": power_timeline,
        # Every remaining/near-future draft pick leaguewide, valued and
        # owner-tagged (see pick_trade_values) - league-wide like
        # team_power_timeline above, not per-team, since a pick's owner is
        # already a column rather than something a team selector filters.
        "pick_trade_values": pick_values,
        # Every team's roster dict, keyed by roster_id - exposed so a UI can
        # run team_roster_analysis() on demand for any team, not just the
        # user's own (see the Roster tab's team selector).
        "rosters_by_id": {r["roster_id"]: r for r in rosters},
        "user_roster_id": user_roster_id,
        # Taxi/IR players from the user's real roster - never eligible for a
        # starting slot (Sleeper doesn't allow it). Exposed at this level so
        # a UI can call best_position_relevant_drop() on demand for a
        # specific candidate, the same ineligible_ids multi_round_plan uses
        # internally for its own per-round simulation.
        "ineligible_ids": frozenset(user_roster.get("taxi") or []) | frozenset(user_roster.get("reserve") or []),
        "ownership": ownership,
        "current_pick_no": current_pick_no,
        "picks_until_turn": picks_until_turn(ownership, user_roster_id, current_pick_no),
        "your_picks": format_your_picks(ownership, user_roster_id, current_pick_no, team_names),
        **user_analysis,
        # Short "what needs a look right now" digest (see summary.py) - built
        # entirely from user_analysis fields already in this dict, not a new
        # signal. Pick timing/data_warnings aren't part of it - both are
        # already surfaced globally above every tab in streamlit_app.py.
        "attention_digest": attention_digest,
        "recent_picks": pd.DataFrame(recent_rows),
        "big_board": big_board,
        "multi_round_plan": multi_round_plan(
            ownership,
            user_roster_id,
            current_pick_no,
            available,
            players,
            fc_by_sleeper_id,
            user_roster,
            league,
            byes,
            handcuffs,
            real_picks_by_overall,
            draft_snapshot,
        ),
        "team_names": team_names,
        "data_warnings": data_warnings,
    }
