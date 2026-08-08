"""Shared logic for the Sleeper dynasty league tools.

Pulls league/draft/roster state from Sleeper plus dynasty values from
FantasyCalc, and computes the rookie draft big board and roster-needs
summary. Used by both the CLI (`rookie_draft.py`) and the Streamlit
dashboard (`streamlit_app.py`) so the two stay in sync on one code path.

Split into submodules by concern (pick ownership, player pools, roster
needs, power/timeline, capacity, roster value, byes/handcuffs, lineup,
drop recommendation, trade evaluation, draft planning, orchestration).
This file just re-exports the combined public surface so `import
dynasty_core` behaves exactly as it did as a single file.
"""

from __future__ import annotations

# Re-exported for callers that reach through dynasty_core (e.g.
# monkeypatching dynasty_core.sleeper in tests) rather than importing
# sleeper_api/fantasycalc_api directly.
import fantasycalc_api as fantasycalc
import sleeper_api as sleeper

from .byes import (
    BYES_CACHE_TTL_SECONDS,
    bye_week_by_team,
    gap_delta,
    recent_complete_seasons_weekly_data,
    roster_bye_conflicts,
    roster_weekly_gaps,
)
from .constants import (
    CACHE_DIR,
    DEFAULT_LEAGUE_ID,
    DEFAULT_USERNAME,
    FANTASY_POSITIONS,
    FLEX_ELIGIBLE_POSITIONS,
    NFL_WEEKS,
    SUPERFLEX_ELIGIBLE_POSITIONS,
    YOUNG_CORE_NEED_THRESHOLD,
)
from .draft_plan import (
    MAX_DISPLAYED_ALTERNATES,
    alternate_gap_note,
    hypothetical_needs_and_handcuffs,
    multi_round_plan,
)
from .draft_snapshots import AMBIGUOUS, reconcile_snapshot
from .handcuffs import HANDCUFFS_CACHE_TTL_SECONDS, handcuff_map, handcuff_targets, roster_handcuff_status
from .lineup import (
    assign_starters,
    bye_for_row,
    lineup_breakdown,
    player_value_rows,
    roster_capacity,
    roster_total_capacity,
)
from .marginal_value import (
    best_position_relevant_drop,
    free_agent_board,
    rank_by_marginal_value,
    recommend_drop,
    season_average_starter_value,
)
from .picks import (
    FUTURE_PICK_YEARS_AHEAD,
    ROUND_ORDINAL,
    DraftPickSlot,
    _future_pick_owners,
    compute_pick_ownership,
    format_your_picks,
    own_draft_picks,
    pick_trade_values,
    picks_until_turn,
    resolve_user_roster_id,
    team_name_by_roster_id,
)
from .player_pools import (
    POSITION_VALUE_MULTIPLIER,
    _resolve_multiplier,
    build_big_board,
    fc_value_by_sleeper_id,
    free_agent_pool,
    rookie_pool,
    roster_fantasy_players,
    rostered_player_ids,
)
from .power_timeline import (
    PHASE_THRESHOLDS,
    WIN_PCT_SHRINKAGE_K,
    _shrunk_win_pct,
    _weighted_average_age,
    team_power_timeline_scores,
)
from .roster_needs import (
    YOUNG_CORE_MAX_YOE,
    _position_starter_demand,
    need_positions,
    position_replacement_levels,
    positional_strength_summary,
    roster_needs_summary,
)
from .roster_value import (
    DEFAULT_LOW_VALUE_AGING_AGE,
    INJURY_STATUS_DESCRIPTIONS,
    LOW_VALUE_AGING_AGE,
    LOW_VALUE_YOUNG_AGE,
    player_status_details,
    player_status_flags,
    roster_value_analysis,
)
from .state import gather_state
from .team_analysis import team_roster_analysis
from .trade import (
    TRADE_OFFER_MAX_COMBO_SIZE,
    TRADE_OFFER_MIN_ABSOLUTE_TOLERANCE,
    TRADE_OFFER_PARTNER_TOLERANCE_PCT,
    TRADE_OFFER_POOL_CAP,
    TRADE_OFFER_PREFILTER_HIGH,
    TRADE_OFFER_PREFILTER_LOW,
    evaluate_trade,
    find_trade_offers,
    sellable_players,
)

__all__ = [
    "AMBIGUOUS",
    "BYES_CACHE_TTL_SECONDS",
    "CACHE_DIR",
    "DEFAULT_LEAGUE_ID",
    "DEFAULT_LOW_VALUE_AGING_AGE",
    "DEFAULT_USERNAME",
    "FANTASY_POSITIONS",
    "FLEX_ELIGIBLE_POSITIONS",
    "FUTURE_PICK_YEARS_AHEAD",
    "HANDCUFFS_CACHE_TTL_SECONDS",
    "INJURY_STATUS_DESCRIPTIONS",
    "LOW_VALUE_AGING_AGE",
    "LOW_VALUE_YOUNG_AGE",
    "MAX_DISPLAYED_ALTERNATES",
    "NFL_WEEKS",
    "PHASE_THRESHOLDS",
    "POSITION_VALUE_MULTIPLIER",
    "ROUND_ORDINAL",
    "SUPERFLEX_ELIGIBLE_POSITIONS",
    "TRADE_OFFER_MAX_COMBO_SIZE",
    "TRADE_OFFER_MIN_ABSOLUTE_TOLERANCE",
    "TRADE_OFFER_PARTNER_TOLERANCE_PCT",
    "TRADE_OFFER_POOL_CAP",
    "TRADE_OFFER_PREFILTER_HIGH",
    "TRADE_OFFER_PREFILTER_LOW",
    "WIN_PCT_SHRINKAGE_K",
    "YOUNG_CORE_MAX_YOE",
    "YOUNG_CORE_NEED_THRESHOLD",
    "DraftPickSlot",
    "_future_pick_owners",
    "_position_starter_demand",
    "_resolve_multiplier",
    "_shrunk_win_pct",
    "_weighted_average_age",
    "alternate_gap_note",
    "assign_starters",
    "best_position_relevant_drop",
    "build_big_board",
    "bye_for_row",
    "bye_week_by_team",
    "compute_pick_ownership",
    "evaluate_trade",
    "fantasycalc",
    "fc_value_by_sleeper_id",
    "find_trade_offers",
    "format_your_picks",
    "free_agent_board",
    "free_agent_pool",
    "gap_delta",
    "gather_state",
    "handcuff_map",
    "handcuff_targets",
    "hypothetical_needs_and_handcuffs",
    "lineup_breakdown",
    "multi_round_plan",
    "need_positions",
    "own_draft_picks",
    "pick_trade_values",
    "picks_until_turn",
    "player_status_details",
    "player_status_flags",
    "player_value_rows",
    "position_replacement_levels",
    "positional_strength_summary",
    "rank_by_marginal_value",
    "recent_complete_seasons_weekly_data",
    "reconcile_snapshot",
    "recommend_drop",
    "resolve_user_roster_id",
    "rookie_pool",
    "roster_bye_conflicts",
    "roster_capacity",
    "roster_fantasy_players",
    "roster_handcuff_status",
    "roster_needs_summary",
    "roster_total_capacity",
    "roster_value_analysis",
    "roster_weekly_gaps",
    "rostered_player_ids",
    "season_average_starter_value",
    "sellable_players",
    "sleeper",
    "team_name_by_roster_id",
    "team_power_timeline_scores",
    "team_roster_analysis",
]
