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

# Position-level correction for FantasyCalc's known scoring mismatch (see
# PROJECT_PLAN.md): FantasyCalc's values assume 4pt passing TDs and no TE
# premium, not this league's real 6pt passing TDs / +0.5-per-reception TE
# premium. Computed from real 2024 season data (the most recent complete
# season nfl_data_py has published — 2025 isn't available yet) as the ratio
# of total fantasy points, under this league's real rule vs FantasyCalc's
# assumed baseline rule, holding every other scoring setting constant, for
# startable-volume players (QB: >=200 attempts, 39 qualifying; TE: >=30
# targets, 45 qualifying). This corrects only the two largest, most clearly
# attributable gaps — it does NOT correct for the smaller long-TD/first-down
# bonus gaps also noted in PROJECT_PLAN.md. A real per-player recompute
# (Phase 4) would replace this; this is the deliberately lightweight version.
POSITION_VALUE_MULTIPLIER = {
    "QB": 1.164,
    "TE": 1.204,
}


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


def adjusted_value(position: str, value: float | None) -> float | None:
    """Apply the QB/TE scoring-mismatch correction to a raw FantasyCalc value."""
    if value is None:
        return None
    return value * POSITION_VALUE_MULTIPLIER.get(position, 1.0)


def build_big_board(
    available: dict[str, dict],
    fc_values: list[dict],
    need_positions: frozenset[str] = frozenset(),
    handcuff_targets: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Rank available rookies by dynasty value into tiers, for display.

    `value` is FantasyCalc's raw number; `adj_value` applies the QB/TE
    scoring-mismatch correction (see POSITION_VALUE_MULTIPLIER) and is what
    determines sort order and `rank`. `tier` is FantasyCalc's own global
    tier across *all* dynasty-relevant players, not rookie-specific and not
    adjusted — gaps in the tier sequence here are veterans/other rookies not
    in this filtered view. `rank` is this player's order within this
    rookie-only list by adj_value (1 = best available rookie). `fits_need`
    flags whether the player's position is currently a roster need (see
    `roster_needs_summary`) — a rough prioritization signal, not a single
    "correct" pick. `handcuff_to` names the roster's own RB starter this
    rookie would handcuff, if any (see `handcuff_map`).
    """
    fc_by_sleeper_id = {
        entry["player"]["sleeperId"]: entry for entry in fc_values if entry["player"].get("sleeperId")
    }
    handcuff_targets = handcuff_targets or {}

    rows = []
    for player_id, info in available.items():
        fc_entry = fc_by_sleeper_id.get(player_id)
        position = info.get("position")
        value = fc_entry["value"] if fc_entry else None
        rows.append(
            {
                "name": info.get("full_name"),
                "pos": position,
                "fits_need": position in need_positions,
                "handcuff_to": handcuff_targets.get(player_id, ""),
                "team": info.get("team") or "FA",
                "college": info.get("college"),
                "age": info.get("age"),
                "value": value,
                "adj_value": adjusted_value(position, value),
                "tier": fc_entry.get("maybeTier") if fc_entry else None,
            }
        )

    board = pd.DataFrame(rows)
    if board.empty:
        return board

    board = board.sort_values("adj_value", ascending=False, na_position="last").reset_index(drop=True)
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

    Uses the same FantasyCalc values as the rookie big board, with the same
    `adj_value` QB/TE correction applied (see POSITION_VALUE_MULTIPLIER) —
    ranking and the low-value cutoff below both use `adj_value`, not the raw
    `value`. `bye` is included for cross-reference against
    `roster_bye_conflicts`.

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
        value = fc_entry["value"] if fc_entry else None
        rows.append(
            {
                "name": info.get("full_name"),
                "pos": position,
                "age": info.get("age"),
                "years_exp": info.get("years_exp"),
                "bye": byes.get(info.get("team")),
                "value": value,
                "adj_value": adjusted_value(position, value),
            }
        )

    roster_df = pd.DataFrame(rows)
    if roster_df.empty:
        return roster_df

    roster_df = roster_df.sort_values("adj_value", ascending=True, na_position="first").reset_index(drop=True)
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


NFL_WEEKS = range(1, 19)


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
    for player_id in roster.get("players") or []:
        info = players.get(player_id, {})
        position = info.get("position")
        if position not in FANTASY_POSITIONS:
            continue
        position_totals[position] += 1
        bye = byes.get(info.get("team"))
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


FLEX_ELIGIBLE_POSITIONS = frozenset({"RB", "WR", "TE"})
SUPERFLEX_ELIGIBLE_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})


def player_value_rows(player_ids: list[str], players: dict[str, dict], fc_values: list[dict]) -> list[dict]:
    """Build {player_id, pos, adj_value} rows for the given players, for lineup/drop logic."""
    fc_by_sleeper_id = {
        entry["player"]["sleeperId"]: entry for entry in fc_values if entry["player"].get("sleeperId")
    }
    rows = []
    for player_id in player_ids:
        info = players.get(player_id, {})
        position = info.get("position")
        if position not in FANTASY_POSITIONS:
            continue
        fc_entry = fc_by_sleeper_id.get(player_id)
        value = fc_entry["value"] if fc_entry else None
        rows.append({"player_id": player_id, "pos": position, "adj_value": adjusted_value(position, value)})
    return rows


def assign_starters(player_rows: list[dict], roster_positions: list[str]) -> list[tuple[str, str | None]]:
    """Assign players to starting slots, most-restrictive slot first.

    Provably optimal for this league's nested slot eligibility: QB's single
    dedicated slot is a subset of SUPER_FLEX's eligible positions, and
    RB/WR/TE dedicated slots are a subset of FLEX's, which is in turn a
    subset of SUPER_FLEX's — filling the most-restrictive slots first with
    the single best remaining value at each step is optimal for this nested
    ("laminar") structure, not just a heuristic (a greedy exchange argument
    applies: filling a less-restrictive slot first could only ever waste a
    flexible slot's optionality on a player who had nowhere else to go).

    Returns one (slot_label, player_id) pair per starting slot in
    roster_positions (excluding bench), in QB/RB/WR/TE/FLEX/SUPER_FLEX
    order; player_id is None if no eligible player remains for that slot.
    """
    remaining = sorted(
        (r for r in player_rows if r["pos"] in FANTASY_POSITIONS),
        key=lambda r: r["adj_value"] if r["adj_value"] is not None else -1,
        reverse=True,
    )

    def take_best(eligible: frozenset[str]) -> str | None:
        for i, row in enumerate(remaining):
            if row["pos"] in eligible:
                return remaining.pop(i)["player_id"]
        return None

    assignments: list[tuple[str, str | None]] = []
    for pos in ("QB", "RB", "WR", "TE"):
        for _ in range(roster_positions.count(pos)):
            assignments.append((pos, take_best(frozenset({pos}))))
    for _ in range(roster_positions.count("FLEX")):
        assignments.append(("FLEX", take_best(FLEX_ELIGIBLE_POSITIONS)))
    for _ in range(roster_positions.count("SUPER_FLEX")):
        assignments.append(("SUPER_FLEX", take_best(SUPERFLEX_ELIGIBLE_POSITIONS)))
    return assignments


def lineup_breakdown(
    roster: dict, players: dict[str, dict], fc_values: list[dict], league: dict
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (starters, bench) for the roster's optimal lineup by current value.

    A snapshot assessment, not week-specific — doesn't yet account for byes
    or injuries when deciding who starts (a by-week/injury-aware version is
    a planned refinement, not built here).
    """
    rows = player_value_rows(roster.get("players") or [], players, fc_values)
    value_by_id = {r["player_id"]: r["adj_value"] for r in rows}
    assignments = assign_starters(rows, league["roster_positions"])
    starter_ids = {pid for _, pid in assignments if pid}

    starter_rows = []
    for slot, pid in assignments:
        if pid is None:
            starter_rows.append({"slot": slot, "name": "(empty)", "pos": None, "adj_value": None})
            continue
        info = players.get(pid, {})
        starter_rows.append(
            {"slot": slot, "name": info.get("full_name"), "pos": info.get("position"), "adj_value": value_by_id[pid]}
        )

    bench_rows = [
        {"name": players.get(r["player_id"], {}).get("full_name"), "pos": r["pos"], "adj_value": r["adj_value"]}
        for r in rows
        if r["player_id"] not in starter_ids
    ]
    bench_df = pd.DataFrame(bench_rows)
    if not bench_df.empty:
        bench_df = bench_df.sort_values("adj_value", ascending=False, na_position="last").reset_index(drop=True)

    return pd.DataFrame(starter_rows), bench_df


def recommend_drop(
    player_ids: list[str],
    players: dict[str, dict],
    fc_values: list[dict],
    league: dict,
    exclude_ids: frozenset[str] = frozenset(),
) -> dict[str, Any] | None:
    """Recommend the single best player to drop: lowest-value bench player, over starters.

    `exclude_ids` protects specific players (e.g. just picked earlier in the
    same multi-round plan) from being recommended for drop in this pass.
    """
    rows = [r for r in player_value_rows(player_ids, players, fc_values) if r["player_id"] not in exclude_ids]
    if not rows:
        return None

    assignments = assign_starters(rows, league["roster_positions"])
    starter_ids = {pid for _, pid in assignments if pid}
    bench_rows = [r for r in rows if r["player_id"] not in starter_ids]
    pool = bench_rows if bench_rows else rows
    worst = min(pool, key=lambda r: r["adj_value"] if r["adj_value"] is not None else -1)

    return {
        "player_id": worst["player_id"],
        "name": players.get(worst["player_id"], {}).get("full_name"),
        "pos": worst["pos"],
        "adj_value": worst["adj_value"],
        "is_starter": worst["player_id"] in starter_ids,
    }


def multi_round_plan(
    ownership: list[DraftPickSlot],
    user_roster_id: int,
    current_pick_no: int,
    available: dict[str, dict],
    players: dict[str, dict],
    fc_values: list[dict],
    user_roster: dict,
    league: dict,
    byes: dict[str, int],
) -> dict[str, Any]:
    """Simulate the user's own remaining picks this draft, round by round.

    For each upcoming pick (in round order): recommends the best available
    rookie by adj_value, and a corresponding drop (bench preferred over
    starters, via assign_starters/recommend_drop), then updates the
    hypothetical roster before simulating the next pick. Does NOT simulate
    the other ~11 teams' picks that happen in between — this assumes "if
    these were your only picks, back to back, on the board as it looks
    right now," not a full mock draft. It's recomputed fresh on every
    refresh, so it stays realistic as the real draft actually progresses.

    Also compares the resulting hypothetical roster's weekly gaps against
    the current roster's (see roster_weekly_gaps), flagging any week where
    this plan would introduce or worsen a dedicated-slot gap.
    """
    own_upcoming = sorted(
        (p for p in ownership if p.owner_roster_id == user_roster_id and p.overall_pick >= current_pick_no),
        key=lambda p: p.overall_pick,
    )

    available_ids = set(available.keys())
    hypothetical_ids = list(user_roster.get("players") or [])
    just_picked: set[str] = set()

    rounds = []
    for pick in own_upcoming:
        rows = player_value_rows(list(available_ids), players, fc_values)
        if not rows:
            break
        best = max(rows, key=lambda r: r["adj_value"] if r["adj_value"] is not None else -1)
        picked_id = best["player_id"]
        picked_info = players.get(picked_id, {})

        drop = recommend_drop(hypothetical_ids, players, fc_values, league, exclude_ids=frozenset(just_picked))

        rounds.append(
            {
                "round": pick.round,
                "overall_pick": pick.overall_pick,
                "pick_name": picked_info.get("full_name"),
                "pick_pos": picked_info.get("position"),
                "pick_adj_value": best["adj_value"],
                "drop_name": drop["name"] if drop else None,
                "drop_pos": drop["pos"] if drop else None,
                "drop_is_starter": drop["is_starter"] if drop else None,
            }
        )

        available_ids.discard(picked_id)
        if drop:
            hypothetical_ids = [pid for pid in hypothetical_ids if pid != drop["player_id"]]
        hypothetical_ids.append(picked_id)
        just_picked.add(picked_id)

    hypothetical_roster = {"players": hypothetical_ids}
    projected_gaps = roster_weekly_gaps(hypothetical_roster, players, byes, league)
    current_gaps = roster_weekly_gaps(user_roster, players, byes, league)
    merged = current_gaps[["week", "gap"]].merge(
        projected_gaps[["week", "gap"]], on="week", suffixes=("_current", "_projected")
    )
    alerts = merged[(merged["gap_projected"] != "") & (merged["gap_projected"] != merged["gap_current"])]

    return {"rounds": pd.DataFrame(rounds), "weekly_gap_alerts": alerts.reset_index(drop=True)}


def draft_strategy_recommendation(big_board: pd.DataFrame, roster_value: pd.DataFrame) -> dict[str, Any]:
    """Synthesize a top pick recommendation and drop candidates, with reasons.

    A heuristic synthesis of signals already computed elsewhere (fits_need,
    handcuff_to, adj_value, the age-aware drop note) into one recommended
    action — not a new valuation model, and not a claim of certainty. Both
    inputs already carry the QB/TE scoring correction via adj_value.
    """
    recommendation: dict[str, Any] = {"top_pick": None, "also_consider": pd.DataFrame(), "drop_candidates": pd.DataFrame()}

    if not big_board.empty:
        need_fits = big_board[big_board["fits_need"]]
        pool = need_fits if not need_fits.empty else big_board
        top = pool.iloc[0]

        reasons = []
        if top["fits_need"]:
            reasons.append(f"fills a flagged need at {top['pos']}")
        else:
            reasons.append("no positions are currently flagged as a need, so this is simply the best value available")
        if top["handcuff_to"]:
            reasons.append(f"also handcuffs your own {top['handcuff_to']}")

        recommendation["top_pick"] = {
            "name": top["name"],
            "pos": top["pos"],
            "rank": int(top["rank"]),
            "tier": int(top["tier"]),
            "reason": "; ".join(reasons),
        }
        recommendation["also_consider"] = big_board[big_board["name"] != top["name"]].head(3)

    if not roster_value.empty:
        drop_candidates = roster_value[roster_value["note"].str.contains("drop candidate", na=False)]
        if drop_candidates.empty:
            drop_candidates = roster_value.head(1)
        recommendation["drop_candidates"] = drop_candidates

    return recommendation


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

    big_board = build_big_board(available, fc_values, needs, handcuff_targets)
    roster_value = roster_value_analysis(user_roster, players, fc_values, byes)
    lineup_starters, lineup_bench = lineup_breakdown(user_roster, players, fc_values, league)

    return {
        "league": league,
        "ownership": ownership,
        "current_pick_no": current_pick_no,
        "your_picks": format_your_picks(ownership, user_roster_id, current_pick_no, team_names),
        "roster_needs": roster_needs,
        "need_positions": needs,
        "roster_capacity": roster_capacity(user_roster, league),
        "roster_value": roster_value,
        "roster_bye_conflicts": roster_bye_conflicts(user_roster, players, byes),
        "roster_weekly_gaps": roster_weekly_gaps(user_roster, players, byes, league),
        "roster_handcuffs": roster_handcuff_status(user_roster, players, handcuffs),
        "lineup_starters": lineup_starters,
        "lineup_bench": lineup_bench,
        "recent_picks": pd.DataFrame(recent_rows),
        "big_board": big_board,
        "strategy": draft_strategy_recommendation(big_board, roster_value),
        "multi_round_plan": multi_round_plan(
            ownership, user_roster_id, current_pick_no, available, players, fc_values, user_roster, league, byes
        ),
        "team_names": team_names,
    }
