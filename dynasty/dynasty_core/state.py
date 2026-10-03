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
from .marginal_value import rank_by_marginal_value
from .picks import (
    compute_pick_ownership,
    format_your_picks,
    own_draft_picks,
    pick_trade_values,
    picks_until_turn,
    resolve_user_roster_id,
    team_name_by_roster_id,
)
from .pickup_snapshots import reconcile_pickup_snapshot
from .player_pools import (
    build_big_board,
    fantasy_relevant_teamed_players,
    fc_value_by_sleeper_id,
    free_agent_pool,
    rookie_pool,
    rostered_player_ids,
)
from .power_timeline import team_power_timeline_scores
from .roster_needs import position_replacement_levels
from .summary import build_attention_digest
from .team_analysis import team_roster_analysis
from .trade import leaguewide_trade_candidates

logger = logging.getLogger(__name__)


def build_pickup_alerts(pickup_changes: list[dict], ranked: list[dict], players: dict[str, dict]) -> list[dict]:
    """Add marginal value and drop context to pickup changes; keep positive rounded values, best first."""
    ranked_by_id = {r["player_id"]: r for r in ranked}
    pickup_alerts = []
    for change in pickup_changes:
        ranked_row = ranked_by_id.get(change["player_id"])
        value = round(ranked_row["marginal_value"], 1) if ranked_row else None
        if value is not None and value > 0:
            info = players.get(change["player_id"], {})
            drop = ranked_row["drop"]
            pickup_alerts.append(
                {
                    **change,
                    "name": info.get("full_name"),
                    "pos": info.get("position"),
                    "team": info.get("team"),
                    "marginal_value": value,
                    "drop_name": drop["name"] if drop else None,
                    "drop_is_starter": drop["is_starter"] if drop else None,
                }
            )
    pickup_alerts.sort(key=lambda a: a["marginal_value"], reverse=True)
    return pickup_alerts


def gather_state(
    league_id: str, username: str, force_full_refresh: bool, force_scoring_refresh: bool = False
) -> dict[str, Any]:
    """Pull league and draft state and compute everything the app shows.

    `force_full_refresh` busts the slow API caches. `force_scoring_refresh` separately
    recomputes scoring multipliers (1-2 min), so a routine refresh can't freeze the app
    mid-draft.
    """
    # Name the failing service; on draft day either can be down.
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

    # Optional enrichments: a failure falls back and adds a data warning instead of breaking the refresh.
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
    try:
        transactions = sleeper.get_transactions(
            league_id, league["season"], league["settings"].get("leg", 1), force_refresh=force_full_refresh
        )
    except Exception:
        logger.warning("Failed to fetch transaction history; skipping FAAB bid guidance", exc_info=True)
        transactions = []
        data_warnings.append(
            "Waiver transaction history unavailable this refresh - FAAB bid guidance will show no "
            "comparable bids, which does not mean there aren't any."
        )

    projection_week = league["settings"].get("leg", 1)
    try:
        projections = sleeper.get_weekly_projections(league["season"], projection_week, force_refresh=force_full_refresh)
    except Exception:
        logger.warning("Failed to fetch weekly projections; skipping this-week lineup mode", exc_info=True)
        projections = {}
        data_warnings.append(
            "This week's player projections are unavailable this refresh - the Lineup tab's "
            "\"this week's projected lineup\" mode will show no ranking, which does not mean "
            "the players themselves are unavailable."
        )

    user_roster_id = resolve_user_roster_id(users, rosters, username)
    team_names = team_name_by_roster_id(rosters, users)
    user_roster = next(r for r in rosters if r["roster_id"] == user_roster_id)

    user_handcuff_targets = handcuff_targets(user_roster.get("players") or [], players, handcuffs)
    # Taxi/IR players can never start.
    ineligible_ids = frozenset(user_roster.get("taxi") or []) | frozenset(user_roster.get("reserve") or [])

    ownership = compute_pick_ownership(draft, traded_picks, league["season"])
    picked_player_ids = {p["player_id"] for p in draft_picks if p.get("player_id")}
    current_pick_no = len(draft_picks) + 1
    # Decode with the draft's own teams/rounds, matching compute_pick_ownership's encoding.
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
    # A FantasyCalc pick-naming change would blank every value without raising.
    if not pick_values.empty and pick_values["value"].isna().all():
        data_warnings.append(
            "Draft pick trade values unavailable this refresh - couldn't match any pick to "
            "FantasyCalc's current pick names, which may mean their naming convention changed."
        )

    unavailable = rostered_player_ids(rosters) | picked_player_ids
    rookies = rookie_pool(players, league["season"])
    available = {pid: info for pid, info in rookies.items() if pid not in unavailable}

    # Exclude only rookies rostered outside this draft; drafted ones stay with attribution.
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

    own_picks = own_draft_picks(ownership, user_roster_id)
    draft_snapshot = reconcile_snapshot(
        league["draft_id"], own_picks, current_pick_no, user_roster.get("players") or [], real_picks_by_overall
    )

    # Undrafted rookies aren't free agents while the draft has picks left.
    total_draft_picks = draft["settings"]["teams"] * draft["settings"]["rounds"]
    draft_eligible_rookie_ids = frozenset() if current_pick_no > total_draft_picks else frozenset(available.keys())
    available_free_agents = free_agent_pool(players, rosters, draft_eligible_rookie_ids)

    # Changes across the whole teamed population, filtered to available players, then ranked
    # uncapped so a real pickup outside the board's top 25 isn't missed.
    _, pickup_changes = reconcile_pickup_snapshot(
        league_id, league["season"], fantasy_relevant_teamed_players(players)
    )
    pickup_changes = [c for c in pickup_changes if c["player_id"] in available_free_agents]
    pickup_alerts = []
    if pickup_changes:
        changed_ids = [c["player_id"] for c in pickup_changes]
        ranked = rank_by_marginal_value(
            changed_ids,
            user_roster.get("players") or [],
            players,
            fc_by_sleeper_id,
            byes,
            league,
            top_n=len(changed_ids),
            ineligible_ids=ineligible_ids,
            reserve_filled=len(user_roster.get("reserve") or []),
            taxi_eligible=False,
            taxi_filled=len(user_roster.get("taxi") or []),
        )
        pickup_alerts = build_pickup_alerts(pickup_changes, ranked, players)

    replacement_level = position_replacement_levels(rosters, players, fc_by_sleeper_id, league["roster_positions"])

    # Before the user's team analysis, which needs this team's phase.
    power_timeline = team_power_timeline_scores(rosters, players, fc_by_sleeper_id, replacement_level, league)
    user_phase = str(power_timeline.loc[user_roster_id, "phase"])

    user_analysis = team_roster_analysis(
        user_roster,
        players,
        fc_by_sleeper_id,
        byes,
        league,
        handcuffs,
        replacement_level,
        available_free_agents,
        projections,
        phase=user_phase,
    )

    # Suggested Trades stage 1: cheap enough to run every refresh.
    suggested_trade_candidates = leaguewide_trade_candidates(
        rosters,
        user_roster,
        players,
        fc_by_sleeper_id,
        byes,
        league,
        user_analysis["sellable_players"],
        pick_values,
    )

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
        pickup_alerts,
        league["settings"].get("leg", 1),
    )

    return {
        "league": league,
        "players": players,
        "fc_by_sleeper_id": fc_by_sleeper_id,
        "byes": byes,
        "handcuffs": handcuffs,
        "transactions": transactions,
        # Empty when the fetch failed (see data_warnings).
        "projections": projections,
        "projection_week": projection_week,
        "replacement_level": replacement_level,
        "available_free_agents": available_free_agents,
        # FAAB: waiver_budget minus this roster's waiver_budget_used.
        "user_faab_remaining": (
            league["settings"].get("waiver_budget", 0) - (user_roster.get("settings") or {}).get("waiver_budget_used", 0)
        ),
        "team_power_timeline": power_timeline,
        "pick_trade_values": pick_values,
        "suggested_trade_candidates": suggested_trade_candidates,
        "rosters_by_id": {r["roster_id"]: r for r in rosters},
        "user_roster_id": user_roster_id,
        "ineligible_ids": ineligible_ids,
        "ownership": ownership,
        "current_pick_no": current_pick_no,
        "picks_until_turn": picks_until_turn(ownership, user_roster_id, current_pick_no),
        "your_picks": format_your_picks(ownership, user_roster_id, current_pick_no, team_names),
        **user_analysis,
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
            replacement_level=replacement_level,
            phase=user_phase,
        ),
        "team_names": team_names,
        "data_warnings": data_warnings,
    }
