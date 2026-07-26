"""Shared logic for the Sleeper dynasty league tools.

Pulls league/draft/roster state from Sleeper plus dynasty values from
FantasyCalc, and computes the rookie draft big board and roster-needs
summary. Used by both the CLI (`rookie_draft.py`) and the Streamlit
dashboard (`streamlit_app.py`) so the two stay in sync on one code path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import nfl_data_py as nfl
import pandas as pd

import fantasycalc_api as fantasycalc
import sleeper_api as sleeper

logger = logging.getLogger(__name__)

DEFAULT_LEAGUE_ID = "1324888291937386496"
DEFAULT_USERNAME = "twharris57"
FANTASY_POSITIONS = ("QB", "RB", "WR", "TE")
YOUNG_CORE_MAX_YOE = 2
YOUNG_CORE_NEED_THRESHOLD = 2
LOW_VALUE_YOUNG_AGE = 24
LOW_VALUE_AGING_AGE = 27


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
    """Map roster_id to a display name (team name if set, else Sleeper username)."""
    user_by_id = {u["user_id"]: u for u in users}
    names = {}
    for roster in rosters:
        user = user_by_id.get(roster["owner_id"])
        team_name = (user.get("metadata") or {}).get("team_name") if user else None
        names[roster["roster_id"]] = team_name or (user or {}).get("display_name") or f"Roster {roster['roster_id']}"
    return names


def compute_pick_ownership(draft: dict, traded_picks: list[dict], season: str) -> list[DraftPickSlot]:
    """Return every pick in this draft, in overall-pick order, with trades applied."""
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


def rostered_player_ids(rosters: list[dict]) -> set[str]:
    """Return every player_id currently on any team's roster."""
    ids: set[str] = set()
    for roster in rosters:
        ids.update(roster.get("players") or [])
    return ids


def rookie_pool(players: dict[str, dict], season: str) -> dict[str, dict]:
    """Return this season's rookie class at fantasy-relevant positions."""
    return {
        player_id: info
        for player_id, info in players.items()
        if info.get("position") in FANTASY_POSITIONS
        and (info.get("metadata") or {}).get("rookie_year") == season
    }


def build_big_board(
    available: dict[str, dict],
    fc_values: list[dict],
    need_positions: frozenset[str] = frozenset(),
    handcuff_targets: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Rank available rookies by dynasty value into tiers, for display.

    `tier` is FantasyCalc's global tier across *all* dynasty-relevant
    players, not rookie-specific — gaps in the tier sequence here are
    veterans/other rookies not in this filtered view. `rank` is this
    player's order within this rookie-only list (1 = best available rookie).
    `fits_need` flags whether the player's position is currently a roster
    need (see `roster_needs_summary`) — a rough prioritization signal, not a
    single "correct" pick. `handcuff_to` names the roster's own RB starter
    this rookie would handcuff, if any (see `handcuff_map`).
    """
    fc_by_sleeper_id = {
        entry["player"]["sleeperId"]: entry for entry in fc_values if entry["player"].get("sleeperId")
    }
    handcuff_targets = handcuff_targets or {}

    rows = []
    for player_id, info in available.items():
        fc_entry = fc_by_sleeper_id.get(player_id)
        rows.append(
            {
                "name": info.get("full_name"),
                "pos": info.get("position"),
                "fits_need": info.get("position") in need_positions,
                "handcuff_to": handcuff_targets.get(player_id, ""),
                "team": info.get("team") or "FA",
                "college": info.get("college"),
                "age": info.get("age"),
                "value": fc_entry["value"] if fc_entry else None,
                "tier": fc_entry.get("maybeTier") if fc_entry else None,
            }
        )

    board = pd.DataFrame(rows)
    if board.empty:
        return board

    board = board.sort_values("value", ascending=False, na_position="last").reset_index(drop=True)
    unranked_tier = int(board["tier"].max() + 1) if board["tier"].notna().any() else 1
    board["tier"] = board["tier"].fillna(unranked_tier).astype(int)
    board.insert(0, "rank", board.index + 1)
    return board


def roster_needs_summary(roster: dict, players: dict[str, dict]) -> pd.DataFrame:
    """Summarize the roster by position: depth, average age, and young-core count.

    `need` flags a position where fewer than YOUNG_CORE_NEED_THRESHOLD players
    have YOUNG_CORE_MAX_YOE years of experience or less — a rough signal for
    where a rebuild still needs young talent, not a full needs model.
    """
    rows = []
    for player_id in roster.get("players") or []:
        info = players.get(player_id, {})
        position = info.get("position")
        if position not in FANTASY_POSITIONS:
            continue
        rows.append({"pos": position, "age": info.get("age"), "years_exp": info.get("years_exp")})

    roster_df = pd.DataFrame(rows)
    if roster_df.empty:
        return roster_df

    summary = roster_df.groupby("pos").agg(
        count=("pos", "count"),
        avg_age=("age", "mean"),
        young_core=("years_exp", lambda s: int((s <= YOUNG_CORE_MAX_YOE).sum())),
    )
    summary = summary.reindex(FANTASY_POSITIONS).dropna(how="all")
    summary["need"] = summary["young_core"] < YOUNG_CORE_NEED_THRESHOLD
    return summary.round(1)


def need_positions(roster_needs: pd.DataFrame) -> frozenset[str]:
    """Return the set of positions currently flagged as a roster need."""
    if roster_needs.empty:
        return frozenset()
    return frozenset(roster_needs.index[roster_needs["need"]])


def roster_capacity(roster: dict, league: dict) -> dict[str, int]:
    """Return active-roster and taxi-squad slot usage for the given roster.

    Reserve/IR slots are deliberately not modeled here — how they interact
    with the active-roster count isn't reliably derivable from the Sleeper
    API response alone, and an unclear rule is worse than not showing it.
    """
    all_player_ids = roster.get("players") or []
    taxi_ids = roster.get("taxi") or []

    active_total = len(league["roster_positions"])
    active_filled = len(all_player_ids) - len(taxi_ids)
    taxi_total = league["settings"].get("taxi_slots", 0)
    taxi_filled = len(taxi_ids)

    return {
        "active_total": active_total,
        "active_filled": active_filled,
        "active_open": active_total - active_filled,
        "taxi_total": taxi_total,
        "taxi_filled": taxi_filled,
        "taxi_open": taxi_total - taxi_filled,
    }


def roster_value_analysis(
    roster: dict, players: dict[str, dict], fc_values: list[dict], byes: dict[str, int] | None = None
) -> pd.DataFrame:
    """Rank the roster by dynasty value (lowest first) to surface drop candidates.

    Uses the same FantasyCalc values as the rookie big board — this league's
    known scoring mismatch applies here too (see PROJECT_PLAN.md): QB/TE are
    likely undervalued relative to this league's real 6pt-passing/TE-premium
    rules, so a "low value" QB/TE deserves more skepticism than the number
    alone suggests.

    The bottom quartile (min 3 players) of the roster's own value distribution
    is flagged low-value. Within that group, `note` distinguishes aging
    players (real drop candidates) from young ones (still rebuild assets,
    worth holding for optionality per this team's stated strategy) rather
    than treating "low value" as "drop" outright.
    """
    fc_by_sleeper_id = {
        entry["player"]["sleeperId"]: entry for entry in fc_values if entry["player"].get("sleeperId")
    }
    byes = byes or {}

    rows = []
    for player_id in roster.get("players") or []:
        info = players.get(player_id, {})
        position = info.get("position")
        if position not in FANTASY_POSITIONS:
            continue
        fc_entry = fc_by_sleeper_id.get(player_id)
        rows.append(
            {
                "name": info.get("full_name"),
                "pos": position,
                "age": info.get("age"),
                "years_exp": info.get("years_exp"),
                "bye": byes.get(info.get("team")),
                "value": fc_entry["value"] if fc_entry else None,
            }
        )

    roster_df = pd.DataFrame(rows)
    if roster_df.empty:
        return roster_df

    roster_df = roster_df.sort_values("value", ascending=True, na_position="first").reset_index(drop=True)
    low_value_cutoff = max(3, len(roster_df) // 4)
    is_low_value = roster_df.index < low_value_cutoff

    def note(low_value: bool, age: float | None) -> str:
        if not low_value:
            return ""
        if age is not None and age < LOW_VALUE_YOUNG_AGE:
            return "Low value, young — rebuild upside, hold"
        if age is not None and age >= LOW_VALUE_AGING_AGE:
            return "Low value, aging — drop candidate"
        return "Low value — monitor"

    roster_df["note"] = [note(lv, age) for lv, age in zip(is_low_value, roster_df["age"])]
    return roster_df


def bye_week_by_team(season: str) -> dict[str, int]:
    """Return each NFL team's bye week for the season, derived from the schedule.

    nfl_data_py has no direct "bye week" field — derived as the one week in
    1-18 where a team appears in neither home_team nor away_team.
    """
    schedule = nfl.import_schedules([int(season)])
    regular = schedule[schedule["game_type"] == "REG"]
    all_weeks = set(regular["week"].unique())
    teams = set(regular["home_team"]) | set(regular["away_team"])

    byes: dict[str, int] = {}
    for team in teams:
        played = set(regular.loc[(regular["home_team"] == team) | (regular["away_team"] == team), "week"])
        missing = all_weeks - played
        if len(missing) == 1:
            byes[team] = missing.pop()
    return byes


def roster_bye_conflicts(roster: dict, players: dict[str, dict], byes: dict[str, int]) -> pd.DataFrame:
    """Flag position groups on the roster with 2+ players sharing the same bye week."""
    rows = []
    for player_id in roster.get("players") or []:
        info = players.get(player_id, {})
        position = info.get("position")
        team = info.get("team")
        if position not in FANTASY_POSITIONS or team not in byes:
            continue
        rows.append({"pos": position, "bye": byes[team], "name": info.get("full_name"), "team": team})

    bye_df = pd.DataFrame(rows)
    if bye_df.empty:
        return bye_df

    grouped = bye_df.groupby(["pos", "bye"])["name"].apply(lambda names: ", ".join(sorted(names)))
    counts = bye_df.groupby(["pos", "bye"]).size()
    conflicts = pd.DataFrame({"players": grouped, "count": counts})
    conflicts = conflicts[conflicts["count"] >= 2].reset_index()
    return conflicts.sort_values(["pos", "bye"]).reset_index(drop=True)


def handcuff_map(season: str) -> dict[str, str]:
    """Map each starting RB's sleeper_id to their primary backup's sleeper_id.

    "Starting"/"backup" come from the latest depth-chart snapshot for the
    season — nfl_data_py's depth-chart feed is a time series of scrapes, not
    a single current view, so this filters to the most recent `dt`. Handcuffs
    are an RB-specific fantasy concept; other positions aren't modeled here.
    """
    depth = nfl.import_depth_charts([int(season)])
    latest = depth[depth["dt"] == depth["dt"].max()]
    rb = latest[latest["pos_abb"] == "RB"]

    ids = nfl.import_ids().dropna(subset=["gsis_id", "sleeper_id"])
    gsis_to_sleeper = {row.gsis_id: str(int(row.sleeper_id)) for row in ids.itertuples()}

    handcuffs: dict[str, str] = {}
    for _team, group in rb.groupby("team"):
        ranked = group.sort_values("pos_rank")
        if len(ranked) < 2:
            continue
        starter_id = gsis_to_sleeper.get(ranked.iloc[0]["gsis_id"])
        backup_id = gsis_to_sleeper.get(ranked.iloc[1]["gsis_id"])
        if starter_id and backup_id:
            handcuffs[starter_id] = backup_id
    return handcuffs


def roster_handcuff_status(roster: dict, players: dict[str, dict], handcuffs: dict[str, str]) -> pd.DataFrame:
    """For each rostered RB who is an NFL starter, show whether their handcuff is also rostered."""
    roster_ids = set(roster.get("players") or [])
    rows = []
    for player_id in roster.get("players") or []:
        info = players.get(player_id, {})
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


def gather_state(league_id: str, username: str, force_refresh_players: bool) -> dict[str, Any]:
    """Pull one full snapshot of league + draft state and compute the big board."""
    league = sleeper.get_league(league_id)
    rosters = sleeper.get_rosters(league_id)
    users = sleeper.get_users(league_id)
    draft = sleeper.get_draft(league["draft_id"])
    draft_picks = sleeper.get_draft_picks(league["draft_id"])
    traded_picks = sleeper.get_traded_picks(league_id)
    players = sleeper.get_players(force_refresh=force_refresh_players)

    num_qbs = league["roster_positions"].count("QB") + league["roster_positions"].count("SUPER_FLEX")
    num_teams = league["settings"]["num_teams"]
    ppr = league["scoring_settings"].get("rec", 0)
    fc_values = fantasycalc.get_dynasty_values(num_qbs=num_qbs, num_teams=num_teams, ppr=ppr)

    # Enrichment from nfl_data_py: optional, must not break the core draft
    # board if the feed is unavailable or its schema drifts (it already has
    # once - the 2026 depth chart columns differ from prior seasons).
    try:
        byes = bye_week_by_team(league["season"])
    except Exception:
        logger.warning("Failed to fetch bye weeks; skipping bye-conflict analysis", exc_info=True)
        byes = {}
    try:
        handcuffs = handcuff_map(league["season"])
    except Exception:
        logger.warning("Failed to fetch depth charts; skipping handcuff analysis", exc_info=True)
        handcuffs = {}

    user_roster_id = resolve_user_roster_id(users, rosters, username)
    team_names = team_name_by_roster_id(rosters, users)
    user_roster = next(r for r in rosters if r["roster_id"] == user_roster_id)

    user_rb_ids = {pid for pid in (user_roster.get("players") or []) if players.get(pid, {}).get("position") == "RB"}
    handcuff_targets = {
        backup_id: players.get(starter_id, {}).get("full_name", "")
        for starter_id, backup_id in handcuffs.items()
        if starter_id in user_rb_ids
    }

    ownership = compute_pick_ownership(draft, traded_picks, league["season"])
    picked_player_ids = {p["player_id"] for p in draft_picks if p.get("player_id")}
    current_pick_no = len(draft_picks) + 1

    unavailable = rostered_player_ids(rosters) | picked_player_ids
    rookies = rookie_pool(players, league["season"])
    available = {pid: info for pid, info in rookies.items() if pid not in unavailable}

    roster_needs = roster_needs_summary(user_roster, players)
    needs = need_positions(roster_needs)

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

    return {
        "league": league,
        "ownership": ownership,
        "current_pick_no": current_pick_no,
        "your_picks": format_your_picks(ownership, user_roster_id, current_pick_no, team_names),
        "roster_needs": roster_needs,
        "need_positions": needs,
        "roster_capacity": roster_capacity(user_roster, league),
        "roster_value": roster_value_analysis(user_roster, players, fc_values, byes),
        "roster_bye_conflicts": roster_bye_conflicts(user_roster, players, byes),
        "roster_handcuffs": roster_handcuff_status(user_roster, players, handcuffs),
        "recent_picks": pd.DataFrame(recent_rows),
        "big_board": build_big_board(available, fc_values, needs, handcuff_targets),
        "team_names": team_names,
    }
