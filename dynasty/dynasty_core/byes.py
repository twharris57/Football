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
    """Weekly stats for the latest `lookback` seasons that nfl_data_py has published.

    Probes backward from `current_season - 1`, since published data lags the league's
    season label.
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
    """Each team's bye week: the week in 1-18 it doesn't play. Cached 24h."""
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
    """Per bye week: starters out, their fill-ins, and the lineup-value delta.

    Only active-roster players can fill in. `bench_out` lists bye'd players who weren't starting.
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
                "starters_out": ", ".join(sorted(describe(pid) for pid in starters_out_ids))
                or "(none - only bench players out)",
                "fillers": ", ".join(sorted(describe(pid) for pid in filler_ids)) or "(none - bench absorbs it)",
                "lineup_delta": round(week_value - full_value, 1),
                "bench_out": ", ".join(sorted(describe(pid) for pid in bench_out_ids)) or "(none)",
            }
        )

    weekly_df = pd.DataFrame(weekly_rows)
    if weekly_df.empty:
        return weekly_df
    return weekly_df.sort_values("week").reset_index(drop=True)


def roster_weekly_gaps(roster: dict, players: dict[str, dict], byes: dict[str, int], league: dict) -> pd.DataFrame:
    """Per week, flag dedicated QB/RB/WR/TE slots the roster can't fill. Ignores FLEX/SUPER_FLEX."""
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
    """Weeks where `after_roster` has a dedicated-slot gap `before_roster` didn't."""
    before = roster_weekly_gaps(before_roster, players, byes, league)
    after = roster_weekly_gaps(after_roster, players, byes, league)
    merged = before[["week", "gap"]].merge(after[["week", "gap"]], on="week", suffixes=("_before", "_after"))
    return merged[(merged["gap_after"] != "") & (merged["gap_after"] != merged["gap_before"])]
