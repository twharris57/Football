"""Bye-week data and weekly starter-gap detection."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import nfl_data_py as nfl
import pandas as pd

from .constants import CACHE_DIR, FANTASY_POSITIONS, NFL_WEEKS
from .lineup import assign_starters, bye_for_row, player_value_rows
from .player_pools import roster_fantasy_players

logger = logging.getLogger(__name__)

BYES_CACHE_TTL_SECONDS = 24 * 60 * 60


def recent_complete_seasons_weekly_data(current_season: str, lookback: int = 3) -> pd.DataFrame:
    """Fetch weekly player stats for the most recent `lookback` NFL seasons with real data published.

    nfl_data_py's underlying data lags real-world time independent of a
    league's own season label — a league season of "2026" doesn't mean
    2025 stats are published yet (confirmed directly: they weren't, as of
    when this was written). Probes backward from `current_season - 1` one
    year at a time, so this keeps working next year without a code change,
    rather than a hardcoded season list that goes stale. Used to
    (re-)derive POSITION_VALUE_MULTIPLIER (see
    scripts/derive_position_multipliers.py); will also back the eventual
    full per-player scoring recompute (see PROJECT_PLAN_DYNASTY.md).
    """
    candidate = int(current_season) - 1
    frames = []
    while len(frames) < lookback and candidate > 2000:
        try:
            frames.append(nfl.import_weekly_data([candidate]))
        except Exception:
            logger.info("nfl_data_py has no weekly data for %s yet, trying %s", candidate, candidate - 1)
        candidate -= 1
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def bye_week_by_team(season: str, force_refresh: bool = False) -> dict[str, int]:
    """Return each NFL team's bye week for the season, derived from the schedule.

    nfl_data_py has no direct "bye week" field — derived as the one week in
    1-18 where a team appears in neither home_team nor away_team.

    Cached to disk (24h TTL - a published NFL schedule essentially never
    changes mid-season) so a plain "Refresh" click doesn't re-pull and
    re-derive this from nfl_data_py every time, not just on force-refresh.
    """
    cache_path = CACHE_DIR / f"byes_{season}.json"
    if not force_refresh and cache_path.exists():
        age_seconds = time.time() - cache_path.stat().st_mtime
        if age_seconds < BYES_CACHE_TTL_SECONDS:
            return json.loads(cache_path.read_text(encoding="utf-8"))

    schedule = nfl.import_schedules([int(season)])
    regular = schedule[schedule["game_type"] == "REG"]
    all_weeks = set(regular["week"].unique())
    teams = set(regular["home_team"]) | set(regular["away_team"])

    byes: dict[str, int] = {}
    for team in teams:
        on_bye_mask = (regular["home_team"] == team) | (regular["away_team"] == team)
        played = set(regular["week"][on_bye_mask])
        missing = all_weeks - played
        if len(missing) == 1:
            byes[team] = int(missing.pop())

    CACHE_DIR.mkdir(exist_ok=True)
    cache_path.write_text(json.dumps(byes), encoding="utf-8")
    return byes


def roster_bye_conflicts(
    roster: dict,
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    byes: dict[str, int],
    league: dict,
) -> pd.DataFrame:
    """For each week with an active-roster player on bye, show who's out, who fills
    in, and the resulting delta to optimal starting-lineup value.

    A delta rather than a plain "N players share a bye" headcount, since a
    shared bye at a deep position can be a non-issue while a single bye at a
    thin one costs real lineup value. Only active-roster players are
    eligible for starting slots (taxi/reserve excluded — they can't be
    started to cover a bye). `starters_out`/`fillers` are the at-a-glance
    pair; `bench_out` is separate (bye'd players who weren't starting
    anyway, so they don't move `lineup_delta`) for an expanded UI view.
    """
    taxi_ids = set(roster.get("taxi") or [])
    reserve_ids = set(roster.get("reserve") or [])
    active_ids = [
        pid for pid, _ in roster_fantasy_players(roster, players) if pid not in taxi_ids and pid not in reserve_ids
    ]

    rows = player_value_rows(active_ids, players, fc_by_sleeper_id)
    value_by_id = {r["player_id"]: r["adj_value"] or 0 for r in rows}

    bye_by_player = {r["player_id"]: bye_for_row(r, players, byes) for r in rows}

    full_assignments = assign_starters(rows, league["roster_positions"])
    full_starter_ids = {pid for _, pid in full_assignments if pid}
    full_value = sum(value_by_id.get(pid, 0) for pid in full_starter_ids)

    def describe(pid: str) -> str:
        info = players.get(pid, {})
        return f"{info.get('full_name')} ({info.get('position')})"

    weekly_rows = []
    for week in NFL_WEEKS:
        out_ids = [pid for pid, bye in bye_by_player.items() if bye == week]
        if not out_ids:
            continue
        starters_out_ids = [pid for pid in out_ids if pid in full_starter_ids]
        bench_out_ids = [pid for pid in out_ids if pid not in full_starter_ids]

        week_rows = [r for r in rows if bye_by_player[r["player_id"]] != week]
        week_assignments = assign_starters(week_rows, league["roster_positions"])
        week_starter_ids = {pid for _, pid in week_assignments if pid}
        week_value = sum(value_by_id.get(pid, 0) for pid in week_starter_ids)

        filler_ids = week_starter_ids - full_starter_ids
        weekly_rows.append(
            {
                "week": week,
                # Collapsed-view content: only starters actually bumped out and who
                # replaces them - bench players on bye who weren't starting anyway
                # don't belong in an at-a-glance view (see bench_out for the rest).
                "starters_out": ", ".join(sorted(describe(pid) for pid in starters_out_ids))
                or "(none - only bench players out)",
                "fillers": ", ".join(sorted(describe(pid) for pid in filler_ids)) or "(none - bench absorbs it)",
                "lineup_delta": round(week_value - full_value, 1),
                # Expanded-view-only detail: rostered players on bye who weren't
                # in the full-strength lineup anyway, so they don't move the delta.
                "bench_out": ", ".join(sorted(describe(pid) for pid in bench_out_ids)) or "(none)",
            }
        )

    weekly_df = pd.DataFrame(weekly_rows)
    if weekly_df.empty:
        return weekly_df
    return weekly_df.sort_values("week").reset_index(drop=True)


def roster_weekly_gaps(roster: dict, players: dict[str, dict], byes: dict[str, int], league: dict) -> pd.DataFrame:
    """For each week, count available (non-bye) rostered players per position
    and flag weeks where a dedicated starting slot can't be filled.

    "Dedicated" means the QB/RB/WR/TE counts in `league["roster_positions"]`
    (1/2/2/1 in this league) — this does NOT model FLEX/SUPER_FLEX slots,
    which could pull from other positions. It's a rough weekly-depth signal
    (can this position's own starters be filled from the roster alone), not
    a full lineup-feasibility solver.
    """
    required = {pos: league["roster_positions"].count(pos) for pos in FANTASY_POSITIONS}

    position_bye_weeks: dict[str, list[int]] = {pos: [] for pos in FANTASY_POSITIONS}
    position_totals: dict[str, int] = dict.fromkeys(FANTASY_POSITIONS, 0)
    for player_id, info in roster_fantasy_players(roster, players):
        position = info["position"]
        position_totals[position] += 1
        team = info.get("team")
        bye = byes.get(team) if team else None
        if bye is not None:
            position_bye_weeks[position].append(bye)

    rows = []
    for week in NFL_WEEKS:
        row: dict[str, Any] = {"week": week}
        gaps = []
        for pos in FANTASY_POSITIONS:
            available = position_totals[pos] - position_bye_weeks[pos].count(week)
            row[pos] = available
            if available < required.get(pos, 0):
                gaps.append(pos)
        row["gap"] = ", ".join(gaps)
        rows.append(row)

    return pd.DataFrame(rows)


def gap_delta(
    before_roster: dict, after_roster: dict, players: dict[str, dict], byes: dict[str, int], league: dict
) -> pd.DataFrame:
    """Weeks where after_roster has a dedicated-slot gap that before_roster didn't (or a different one).

    Shared by multi_round_plan (full-plan impact vs. the current real
    roster) and alternate_gap_note (single-alternate impact vs. the
    hypothetical roster entering that round) - same before/after
    weekly-gap comparison, just different roster inputs.
    """
    before = roster_weekly_gaps(before_roster, players, byes, league)
    after = roster_weekly_gaps(after_roster, players, byes, league)
    merged = before[["week", "gap"]].merge(after[["week", "gap"]], on="week", suffixes=("_before", "_after"))
    return merged[(merged["gap_after"] != "") & (merged["gap_after"] != merged["gap_before"])]
