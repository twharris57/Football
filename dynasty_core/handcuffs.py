"""RB handcuff detection."""

from __future__ import annotations

import json
import time

import nfl_data_py as nfl
import pandas as pd

import player_scoring

from .constants import CACHE_DIR
from .player_pools import roster_fantasy_players

HANDCUFFS_CACHE_TTL_SECONDS = 12 * 60 * 60


def handcuff_map(season: str, force_refresh: bool = False) -> dict[str, str]:
    """Map each starting RB's sleeper_id to their primary backup's sleeper_id.

    "Starting"/"backup" come from the latest depth-chart snapshot for the
    season — nfl_data_py's depth-chart feed is a time series of scrapes, not
    a single current view, so this filters to the most recent `dt`. Handcuffs
    are an RB-specific fantasy concept; other positions aren't modeled here.

    Cached to disk (12h TTL, same cadence as sleeper_api's players cache -
    depth charts shift day to day, not minute to minute) so a plain
    "Refresh" click doesn't re-pull and re-derive this every time, not just
    on force-refresh.
    """
    cache_path = CACHE_DIR / f"handcuffs_{season}.json"
    if not force_refresh and cache_path.exists():
        age_seconds = time.time() - cache_path.stat().st_mtime
        if age_seconds < HANDCUFFS_CACHE_TTL_SECONDS:
            return json.loads(cache_path.read_text(encoding="utf-8"))

    depth = nfl.import_depth_charts([int(season)])
    latest = depth[depth["dt"] == depth["dt"].max()]
    rb = latest[latest["pos_abb"] == "RB"]

    gsis_to_sleeper = player_scoring.gsis_to_sleeper_crosswalk()

    handcuffs: dict[str, str] = {}
    for _team, group in rb.groupby("team"):
        ranked = group.sort_values("pos_rank")
        if len(ranked) < 2:
            continue
        starter_id = gsis_to_sleeper.get(ranked.iloc[0]["gsis_id"])
        backup_id = gsis_to_sleeper.get(ranked.iloc[1]["gsis_id"])
        if starter_id and backup_id:
            handcuffs[starter_id] = backup_id

    CACHE_DIR.mkdir(exist_ok=True)
    cache_path.write_text(json.dumps(handcuffs), encoding="utf-8")
    return handcuffs


def roster_handcuff_status(roster: dict, players: dict[str, dict], handcuffs: dict[str, str]) -> pd.DataFrame:
    """For each rostered RB who is an NFL starter, show whether their handcuff is also rostered."""
    roster_ids = set(roster.get("players") or [])
    rows = []
    for player_id, info in roster_fantasy_players(roster, players):
        if info.get("position") != "RB":
            continue
        backup_id = handcuffs.get(player_id)
        if backup_id is None:
            continue
        rows.append(
            {
                "starter": info.get("full_name"),
                "handcuff": players.get(backup_id, {}).get("full_name", "Unknown"),
                "handcuff_rostered": backup_id in roster_ids,
            }
        )
    return pd.DataFrame(rows)
