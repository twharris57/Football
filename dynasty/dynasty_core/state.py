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
    """Attach marginal-value/drop context to each pickup-eligible change and rank by impact, best first.

    Filters to a positive *rounded* marginal_value, matching
    `free_agent_board()`'s own round-then-filter order - a raw value in
    (0, 0.05) would otherwise pass a raw `> 0` check here but still render
    as the self-contradicting "would add +0.0 to your lineup" once
    `summary.py` formats it to one decimal (see
    `valuation_principles.md`'s "a displayed number and the filter gating
    its display must round on the same basis" rule). `drop_name`/
    `drop_is_starter` mirror `free_agent_board()`'s own fields exactly
    (same `rank_by_marginal_value()` "drop" shape) so a pickup alert shows
    the same "what this would replace" context the Free agents board
    already does, not just that something changed.
    """
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
    try:
        # Real FAAB bid history (dynasty_core/waiver_bids.py's
        # calibration source). Passed through raw, not pre-computed into
        # guidance here - a UI only needs bid_guidance() for whichever one
        # free-agent candidate it's currently showing, not all ~25 board
        # rows every refresh.
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

    # This week's per-player projections, for the Lineup tab's
    # "this week's projected lineup" mode - an unofficial, undocumented
    # Sleeper endpoint (see sleeper_api.get_weekly_projections), so this
    # degrades to "unavailable" rather than breaking the refresh if it
    # breaks. Same current-week signal roster_tab.py's bye-impact view
    # already uses, not a new one.
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
    # Taxi/IR players from the user's real roster - never eligible for a
    # starting slot (Sleeper doesn't allow it). Hoisted here (not just
    # computed inline in the return dict below) since the pickup-alert
    # ranking below needs it too.
    ineligible_ids = frozenset(user_roster.get("taxi") or []) | frozenset(user_roster.get("reserve") or [])

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

    # Team/depth-chart/status changes across every fantasy-relevant,
    # NFL-teamed player since the last refresh (see pickup_snapshots.py) -
    # deliberately the full population, not just this refresh's free-agent
    # subset, so a real NFL-team change can be told apart from a player
    # merely re-entering the free-agent pool via a fantasy-roster drop (see
    # valuation_principles.md's "first time seen in this narrower pool"
    # rule). Independent of force_full_refresh, same rationale as
    # draft_snapshot above: accumulated cross-refresh state, not a
    # freshness cache. Filtered down to the current free-agent pool before
    # ranking - only an available player is an actionable pickup, and
    # rank_by_marginal_value assumes its candidates are addable, not still
    # on someone else's roster. Ranked via rank_by_marginal_value() directly
    # on just the (typically small) changed set, uncapped (top_n=len(...)),
    # rather than filtering through user_analysis's own top-25-capped
    # free_agent_board below - a real positive-value change ranked outside
    # that cap would otherwise be silently indistinguishable from "not
    # worth it."
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

    # Computed here (moved up from after leaguewide_trade_candidates below)
    # since the user's own team_roster_analysis() call, right after this,
    # needs this team's own phase for its rebuild-phase-aware `need` flag -
    # z-scoring needs every team's row together regardless of when in the
    # function this runs, so there's no cost to computing it slightly
    # earlier. Cheap for the whole league in one pass (no new API calls,
    # just positional_strength_summary reused per roster).
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

    # Leaguewide "worth pursuing" pre-rank for Suggested Trades - Stage 1
    # of the two-stage design (see trade.py's
    # leaguewide_trade_candidates()/suggested_trades() docstrings for the
    # full cost reasoning). Cheap enough (one batch rank_by_marginal_value()
    # call, same order of magnitude as free_agent_board's existing
    # unconditional per-refresh cost) to compute here every refresh, not
    # gated behind a button - only Stage 2's actual offer search (run
    # on-demand in the tab) is expensive. Reuses user_analysis's own
    # sellable_players() output rather than recomputing it.
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
        # Raw waiver transaction history - a UI computes
        # dynasty_core.bid_guidance() from this on demand, for whichever
        # free-agent candidate is currently selected, not precomputed here
        # for the whole board every refresh.
        "transactions": transactions,
        # This week's raw per-player projections and the week number
        # they're for - a UI computes weekly_lineup_* on demand for
        # whichever team it's showing (see team_roster_analysis) rather than
        # this being precomputed for every team every refresh. Empty dict
        # means the fetch failed this refresh (see data_warnings above), not
        # that no player has a projection.
        "projections": projections,
        "projection_week": projection_week,
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
        # .claude/PROJECT_PLAN_DYNASTY.md). league["settings"]["waiver_budget"] is
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
        # Stage 1 of Suggested Trades - see leaguewide_trade_candidates()'s
        # docstring. The tab's "Scan the league for offers" button runs Stage 2
        # (suggested_trades()) against this list on demand; this part is cheap
        # enough to already be computed here every refresh.
        "suggested_trade_candidates": suggested_trade_candidates,
        # Every team's roster dict, keyed by roster_id - exposed so a UI can
        # run team_roster_analysis() on demand for any team, not just the
        # user's own (see the Roster tab's team selector).
        "rosters_by_id": {r["roster_id"]: r for r in rosters},
        "user_roster_id": user_roster_id,
        # Exposed at this level so a UI can call best_position_relevant_drop()
        # on demand for a specific candidate, the same ineligible_ids
        # multi_round_plan uses internally for its own per-round simulation.
        "ineligible_ids": ineligible_ids,
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
            replacement_level=replacement_level,
            phase=user_phase,
        ),
        "team_names": team_names,
        "data_warnings": data_warnings,
    }
