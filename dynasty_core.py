"""Shared logic for the Sleeper dynasty league tools.

Pulls league/draft/roster state from Sleeper plus dynasty values from
FantasyCalc, and computes the rookie draft big board and roster-needs
summary. Used by both the CLI (`rookie_draft.py`) and the Streamlit
dashboard (`streamlit_app.py`) so the two stay in sync on one code path.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import nfl_data_py as nfl
import pandas as pd

import fantasycalc_api as fantasycalc
import player_scoring
import sleeper_api as sleeper

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / ".cache"
BYES_CACHE_TTL_SECONDS = 24 * 60 * 60
HANDCUFFS_CACHE_TTL_SECONDS = 12 * 60 * 60

DEFAULT_LEAGUE_ID = "1324888291937386496"
DEFAULT_USERNAME = "twharris57"
FANTASY_POSITIONS = ("QB", "RB", "WR", "TE")
YOUNG_CORE_MAX_YOE = 2
YOUNG_CORE_NEED_THRESHOLD = 2
LOW_VALUE_YOUNG_AGE = 24

# Dynasty aging curves differ meaningfully by position - RBs decline earliest,
# QBs latest (and often keep starting well into their mid-30s in a passing
# league like this one) - so a single flat "aging" cutoff either flags RBs
# too late or QBs/TEs too early. Judgment calls, not derived from any league
# rule; revisit by feel, same as the other rebuild-strategy heuristics below.
LOW_VALUE_AGING_AGE = {"RB": 27, "WR": 29, "TE": 30, "QB": 33}
DEFAULT_LOW_VALUE_AGING_AGE = 29

# Position-level correction for FantasyCalc's known scoring mismatch (see
# PROJECT_PLAN.md): FantasyCalc's values assume 4pt passing TDs and no TE
# premium, not this league's real 6pt passing TDs / +0.5-per-reception TE
# premium. Computed as the ratio of total fantasy points, under this
# league's real rule vs FantasyCalc's assumed baseline rule, holding every
# other scoring setting constant, for startable-volume players (QB: >=200
# attempts; TE: >=30 targets), pooled across the 3 most recent complete
# NFL seasons (2022-2024 as of this derivation — see
# recent_complete_seasons_weekly_data()) rather than a single season, to
# reduce single-season noise (108 qualifying QB player-seasons, 135 TE,
# vs. 39/45 from 2024 alone). Re-derive with
# `python scripts/derive_position_multipliers.py` whenever a fresher
# season becomes available — that script uses the same lookback-from-
# current-season logic, so it doesn't need editing to stay current, only
# re-running (see PROJECT_PLAN.md for the longer-term plan to automate
# this fully). This corrects only the two largest, most clearly
# attributable gaps — it does NOT correct for the smaller long-TD/first-down
# bonus gaps also noted in PROJECT_PLAN.md. A real per-player recompute
# (see PROJECT_PLAN.md's Active valuation work) would replace this; this is
# the deliberately lightweight version.
POSITION_VALUE_MULTIPLIER = {
    "QB": 1.175,
    "TE": 1.202,
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
    """Return every pick in this draft, in overall-pick order, with trades applied.

    Assumes a "linear" draft (same slot-to-roster order every round) -
    this league's actual, confirmed draft type. The overall-pick math below
    would silently compute wrong pick ownership under a snake draft (which
    reverses slot order on even rounds) - not implemented, since it's never
    been needed - so this fails loudly instead if that ever changes.
    """
    if draft.get("type") != "linear":
        raise ValueError(
            f"compute_pick_ownership only supports a 'linear' draft type, got {draft.get('type')!r} - "
            "pick ownership math assumes the same slot order every round, which a snake or auction "
            "draft would violate."
        )
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


def roster_fantasy_players(roster: dict, players: dict[str, dict]) -> Iterator[tuple[str, dict]]:
    """Yield (player_id, info) for each of the roster's players at a fantasy-relevant position.

    The shared first step of every roster-analysis function below — what
    counts as "fantasy-relevant" (FANTASY_POSITIONS) is defined once here
    instead of re-checked in each one.
    """
    for player_id in roster.get("players") or []:
        info = players.get(player_id, {})
        if info.get("position") in FANTASY_POSITIONS:
            yield player_id, info


def _resolve_multiplier(sleeper_id: str, position: str, multipliers: dict[str, Any]) -> float:
    """Personalized multiplier (see player_scoring.py) if this player has enough real NFL
    history to trust one; else this year's rookie class's play-style-bucket average, if this
    player is a rookie with a matched combine profile (see player_scoring._derive_rookie_buckets,
    valuation step A); else that position's flat average from the same pooled data; else the
    hardcoded POSITION_VALUE_MULTIPLIER, used only if the whole nfl_data_py enrichment failed
    for this refresh (see gather_state)."""
    per_player = multipliers.get("per_player", {})
    rookie_bucket = multipliers.get("rookie_bucket", {})
    position_average = multipliers.get("position_average", {})
    if sleeper_id in per_player:
        return per_player[sleeper_id]
    if sleeper_id in rookie_bucket:
        return rookie_bucket[sleeper_id]
    return position_average.get(position, POSITION_VALUE_MULTIPLIER.get(position, 1.0))


def fc_value_by_sleeper_id(fc_values: list[dict], multipliers: dict[str, Any] | None = None) -> dict[str, dict]:
    """Build a sleeperId -> FantasyCalc entry lookup once, for reuse across many calls.

    The marginal-value ranking below calls into value-lookup logic thousands
    of times per refresh (every candidate x every week, across rounds) -
    rebuilding this ~475-entry dict on each of those calls would be wasteful.
    Each entry gets its real-scoring-corrected `adj_value` precomputed here
    (see `_resolve_multiplier`/player_scoring.py) so every downstream caller,
    which already threads this dict through, gets it for free.
    """
    multipliers = multipliers or {}
    result: dict[str, dict] = {}
    for entry in fc_values:
        sleeper_id = entry["player"].get("sleeperId")
        if not sleeper_id:
            continue
        position = entry["player"].get("position")
        value = entry.get("value")
        multiplier = _resolve_multiplier(sleeper_id, position, multipliers)
        result[sleeper_id] = {**entry, "adj_value": value * multiplier if value is not None else None}
    return result


def build_big_board(
    rookie_pool_: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    need_positions: frozenset[str] = frozenset(),
    handcuff_targets: dict[str, str] | None = None,
    draft_attribution: dict[str, tuple[int, str]] | None = None,
) -> pd.DataFrame:
    """Rank the rookie class by dynasty value into tiers, for display.

    `rookie_pool_` is the whole class (see `rookie_pool`), not just
    undrafted players — once picked, a player stays on the board rather
    than disappearing, annotated via `draft_attribution`
    (player_id -> (round, team_name)) so the board still shows who took
    whom. `rank` is a continuous value order across the whole class
    (drafted and undrafted together), not just "your priority order" — use
    `drafted_round`/`drafted_by` (both empty if still undrafted) to see
    what's actually still on the board.

    `value` is FantasyCalc's raw number; `adj_value` applies the QB/TE
    scoring-mismatch correction (see POSITION_VALUE_MULTIPLIER) and is what
    determines sort order and `rank`. `tier` is FantasyCalc's own global
    tier across *all* dynasty-relevant players, not rookie-specific and not
    adjusted — gaps in the tier sequence here are veterans/other rookies not
    in this filtered view. `fits_need` flags whether the player's position
    is currently a roster need (see `roster_needs_summary`) — a rough
    prioritization signal, not a single "correct" pick. `handcuff_to` names
    the roster's own RB starter this rookie would handcuff, if any (see
    `handcuff_map`).
    """
    handcuff_targets = handcuff_targets or {}
    draft_attribution = draft_attribution or {}

    rows = []
    for player_id, info in rookie_pool_.items():
        fc_entry = fc_by_sleeper_id.get(player_id)
        position = info.get("position")
        value = fc_entry["value"] if fc_entry else None
        drafted_round, drafted_by = draft_attribution.get(player_id, (None, ""))
        rows.append(
            {
                "name": info.get("full_name"),
                "pos": position,
                "fits_need": position in need_positions,
                "handcuff_to": handcuff_targets.get(player_id, ""),
                "drafted_round": drafted_round,
                "drafted_by": drafted_by,
                "team": info.get("team") or "FA",
                "college": info.get("college"),
                "age": info.get("age"),
                "value": value,
                "adj_value": fc_entry.get("adj_value") if fc_entry else None,
                "tier": fc_entry.get("maybeTier") if fc_entry else None,
            }
        )

    board = pd.DataFrame(rows)
    if board.empty:
        return board

    board["drafted_round"] = board["drafted_round"].astype("Int64")
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
    rows = [
        {"pos": info.get("position"), "age": info.get("age"), "years_exp": info.get("years_exp")}
        for _player_id, info in roster_fantasy_players(roster, players)
    ]

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
    """Return active-roster, taxi-squad, and IR/reserve slot usage for the given roster.

    `roster["reserve"]` (a plain player_id list, same shape as `roster["taxi"]`)
    is reliably derivable after all — confirmed directly against the live
    league, including rosters with IR players populated — so it's counted
    here and excluded from `active_filled`, same as taxi.
    """
    all_player_ids = roster.get("players") or []
    taxi_ids = roster.get("taxi") or []
    reserve_ids = roster.get("reserve") or []

    active_total = len(league["roster_positions"])
    active_filled = len(all_player_ids) - len(taxi_ids) - len(reserve_ids)
    taxi_total = league["settings"].get("taxi_slots", 0)
    taxi_filled = len(taxi_ids)
    reserve_total = league["settings"].get("reserve_slots", 0)
    reserve_filled = len(reserve_ids)

    return {
        "active_total": active_total,
        "active_filled": active_filled,
        "active_open": active_total - active_filled,
        "taxi_total": taxi_total,
        "taxi_filled": taxi_filled,
        "taxi_open": taxi_total - taxi_filled,
        "reserve_total": reserve_total,
        "reserve_filled": reserve_filled,
        "reserve_open": reserve_total - reserve_filled,
    }


def roster_total_capacity(league: dict, reserve_filled: int = 0) -> int:
    """Return the combined active-roster + taxi-squad + occupied-reserve slot count.

    Used to decide whether adding a player genuinely requires a drop, for
    simulated/hypothetical rosters — those are tracked as a flat player-id
    list (see multi_round_plan) with no active/taxi/reserve split, so this
    is the "is there room *anywhere*" signal rather than a precise slot
    type. A newly-drafted rookie is never assumed to land on reserve (that
    requires a real injury designation, unlike taxi, which any rookie
    qualifies for) - so `reserve_filled` (the roster's actual current IR
    headcount, passed by the caller, not the league's full `reserve_slots`
    setting) is added to the ceiling only to properly account for *existing*
    IR occupants, not to manufacture room for a new player who could never
    actually be assigned there. A previous version added the full
    `reserve_slots` setting unconditionally - fixed an earlier bug (an
    existing IR occupant's headcount silently eating into active/taxi
    capacity) but overcorrected: with reserve_slots > 0 and nobody actually
    on IR, that inflated the ceiling by empty slots no rookie could ever
    occupy, silently skipping the drop that should have been forced on
    the first `reserve_slots` picks (found via a live draft-plan bug
    report: the first 2 picks had no drop associated, in a league with 2
    reserve slots and no one on IR). Rookies are assumed taxi-eligible
    (true for every candidate in this draft, since they're all entering
    their first season) — a general accrued-experience eligibility check
    is deferred (see PROJECT_PLAN.md).
    """
    return len(league["roster_positions"]) + league["settings"].get("taxi_slots", 0) + reserve_filled


# Sleeper's real injury_status values include some genuinely cryptic
# abbreviations - expanded here for the hover-tooltip detail (see
# player_status_details). Anything not listed (e.g. "Questionable", "Out")
# is already a plain word and passes through unchanged via .get(x, x).
INJURY_STATUS_DESCRIPTIONS = {
    "PUP": "Physically Unable to Perform",
    "COV": "COVID-19",
    "Sus": "Suspended",
    "NA": "Not Active",
    "DNR": "Did Not Report",
    "IR": "Injured Reserve",
}


def player_status_details(
    player_id: str, info: dict, taxi_ids: set[str], reserve_ids: set[str]
) -> list[tuple[str, str]]:
    """(icon, description) pairs for a player's current situation: rookie/injured/taxi/IR.

    A player can have more than one at once (e.g. a rookie stashed on
    taxi). Kept separate from each icon's own description, rather than
    baked into one compact string, so a caller (see streamlit_app.py) can
    show just the icon with the description as a hover tooltip - `st.dataframe`
    has no per-cell tooltip, only a per-column one, so that table renders
    this as plain HTML instead to get a real one.
    """
    details: list[tuple[str, str]] = []
    if not info.get("years_exp"):
        details.append(("🆕", "Rookie (no NFL experience yet)"))
    injury_status = info.get("injury_status")
    if injury_status:
        details.append(("🏥", INJURY_STATUS_DESCRIPTIONS.get(injury_status, injury_status)))
    if player_id in taxi_ids:
        details.append(("🌱", "Taxi squad"))
    if player_id in reserve_ids:
        details.append(("🩹", "IR / Reserve"))
    return details


def player_status_flags(player_id: str, info: dict, taxi_ids: set[str], reserve_ids: set[str]) -> str:
    """Compact icon-only summary of player_status_details, for plain-text display (the CLI)."""
    return " ".join(icon for icon, _description in player_status_details(player_id, info, taxi_ids, reserve_ids))


def roster_value_analysis(
    roster: dict, players: dict[str, dict], fc_by_sleeper_id: dict[str, dict], byes: dict[str, int] | None = None
) -> pd.DataFrame:
    """Rank the roster by dynasty value (lowest first) to surface drop candidates.

    Uses the same FantasyCalc values as the rookie big board, with the same
    real-scoring correction applied (see `fc_value_by_sleeper_id`) —
    ranking and the low-value cutoff below both use `adj_value`, not the raw
    `value`. `bye` is included for cross-reference against
    `roster_bye_conflicts`. `status` is a compact icon summary (see
    `player_status_flags`) - 🆕 rookie (no NFL experience yet), 🏥 injury,
    🌱 taxi squad, 🩹 IR/reserve - a player can show more than one at once.
    `status_details` carries the same info as (icon, description) pairs
    (see `player_status_details`) for a caller that wants to show each
    icon's specific detail (e.g. the real injury_status word) as a hover
    tooltip rather than cramming it into the icon itself.

    The bottom quartile (min 3 players) of the roster's own value distribution
    is flagged low-value. Within that group, `note` distinguishes aging
    players (real drop candidates) from young ones (still rebuild assets,
    worth holding for optionality per this team's stated strategy) rather
    than treating "low value" as "drop" outright. "Aging" is position-aware
    (see `LOW_VALUE_AGING_AGE`) — RBs decline earlier than QBs/TEs in
    dynasty value, so one flat age cutoff would misjudge either end.
    """
    byes = byes or {}
    taxi_ids = set(roster.get("taxi") or [])
    reserve_ids = set(roster.get("reserve") or [])

    rows = []
    for player_id, info in roster_fantasy_players(roster, players):
        position = info.get("position")
        fc_entry = fc_by_sleeper_id.get(player_id)
        value = fc_entry["value"] if fc_entry else None
        rows.append(
            {
                "name": info.get("full_name"),
                "pos": position,
                "age": info.get("age"),
                "years_exp": info.get("years_exp"),
                "status": player_status_flags(player_id, info, taxi_ids, reserve_ids),
                "status_details": player_status_details(player_id, info, taxi_ids, reserve_ids),
                "bye": byes.get(info.get("team")),
                "value": value,
                "adj_value": fc_entry.get("adj_value") if fc_entry else None,
            }
        )

    roster_df = pd.DataFrame(rows)
    if roster_df.empty:
        return roster_df

    roster_df = roster_df.sort_values("adj_value", ascending=True, na_position="first").reset_index(drop=True)
    low_value_cutoff = max(3, len(roster_df) // 4)
    is_low_value = roster_df.index < low_value_cutoff

    def note(low_value: bool, age: float | None, position: str | None) -> str:
        if not low_value:
            return ""
        if age is not None and age < LOW_VALUE_YOUNG_AGE:
            return "Low value, young — rebuild upside, hold"
        aging_age = LOW_VALUE_AGING_AGE.get(position, DEFAULT_LOW_VALUE_AGING_AGE)
        if age is not None and age >= aging_age:
            return "Low value, aging — drop candidate"
        return "Low value — monitor"

    roster_df["note"] = [
        note(lv, age, pos) for lv, age, pos in zip(is_low_value, roster_df["age"], roster_df["pos"])
    ]
    return roster_df


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
    full per-player scoring recompute (see PROJECT_PLAN.md).
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
        played = set(regular.loc[(regular["home_team"] == team) | (regular["away_team"] == team), "week"])
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

    Replaces a plain "2+ players share a bye" headcount with the number that
    actually matters: two players sharing a bye at a deep position can be a
    non-issue, while a single bye at a thin one can cost real lineup value -
    a -500 week and a -5000 week are very different situations, and only the
    delta itself tells them apart. Only active-roster players are eligible
    for starting slots here (unlike `lineup_breakdown` and the marginal-
    value machinery, which don't yet exclude taxi/reserve - see
    PROJECT_PLAN.md), since a taxi or IR player can't actually be started to
    cover a bye on Sleeper.

    `starters_out`/`fillers` are the at-a-glance pair (a bye'd player who was
    actually starting, and who replaces them) - `bench_out` is a separate
    column for bench players who happen to be on bye too but weren't
    starting anyway, so they don't affect `lineup_delta`. Meant to keep a
    collapsed UI view (see streamlit_app.py) to just the two columns that
    matter, with `bench_out` available for an expanded "show the rest" view.
    """
    taxi_ids = set(roster.get("taxi") or [])
    reserve_ids = set(roster.get("reserve") or [])
    active_ids = [
        pid for pid, _ in roster_fantasy_players(roster, players) if pid not in taxi_ids and pid not in reserve_ids
    ]

    rows = player_value_rows(active_ids, players, fc_by_sleeper_id)
    value_by_id = {r["player_id"]: r["adj_value"] or 0 for r in rows}
    bye_by_player = {r["player_id"]: byes.get(players.get(r["player_id"], {}).get("team")) for r in rows}

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
    for player_id, info in roster_fantasy_players(roster, players):
        position = info["position"]
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


FLEX_ELIGIBLE_POSITIONS = frozenset({"RB", "WR", "TE"})
SUPERFLEX_ELIGIBLE_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})


def player_value_rows(player_ids: list[str], players: dict[str, dict], fc_by_sleeper_id: dict[str, dict]) -> list[dict]:
    """Build {player_id, pos, adj_value} rows for the given players, for lineup/drop logic."""
    rows = []
    for player_id in player_ids:
        info = players.get(player_id, {})
        position = info.get("position")
        if position not in FANTASY_POSITIONS:
            continue
        fc_entry = fc_by_sleeper_id.get(player_id)
        rows.append({"player_id": player_id, "pos": position, "adj_value": fc_entry.get("adj_value") if fc_entry else None})
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
    roster: dict, players: dict[str, dict], fc_by_sleeper_id: dict[str, dict], league: dict
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (starters, bench, taxi, ir) for the roster's optimal lineup by current value.

    A snapshot assessment, not week-specific — doesn't yet account for byes
    or injuries when deciding who starts (a by-week/injury-aware version is
    a planned refinement, not built here). Taxi-squad and IR/reserve players
    are both in `roster["players"]` alongside the real bench, so they're
    split out by cross-referencing `roster["taxi"]`/`roster["reserve"]`
    (both plain player_id lists, same shape - confirmed directly against
    the live league, including rosters with IR players populated) rather
    than left lumped into "bench". They're also excluded from the starter
    assignment itself - Sleeper doesn't allow starting a taxi/IR player, so
    they must not be eligible to "win" a slot here regardless of value.
    """
    taxi_ids = set(roster.get("taxi") or [])
    reserve_ids = set(roster.get("reserve") or [])
    rows = player_value_rows(roster.get("players") or [], players, fc_by_sleeper_id)
    value_by_id = {r["player_id"]: r["adj_value"] for r in rows}
    active_rows = [r for r in rows if r["player_id"] not in taxi_ids and r["player_id"] not in reserve_ids]
    assignments = assign_starters(active_rows, league["roster_positions"])
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

    def group_df(predicate) -> pd.DataFrame:
        rows_for_group = [
            {"name": players.get(r["player_id"], {}).get("full_name"), "pos": r["pos"], "adj_value": r["adj_value"]}
            for r in rows
            if predicate(r["player_id"])
        ]
        group_df_ = pd.DataFrame(rows_for_group)
        if not group_df_.empty:
            group_df_ = group_df_.sort_values("adj_value", ascending=False, na_position="last").reset_index(drop=True)
        return group_df_

    bench_df = group_df(lambda pid: pid not in starter_ids and pid not in taxi_ids and pid not in reserve_ids)
    taxi_df = group_df(lambda pid: pid in taxi_ids)
    reserve_df = group_df(lambda pid: pid in reserve_ids)

    return pd.DataFrame(starter_rows), bench_df, taxi_df, reserve_df


def recommend_drop(
    player_ids: list[str],
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    league: dict,
    exclude_ids: frozenset[str] = frozenset(),
    ineligible_ids: frozenset[str] = frozenset(),
) -> dict[str, Any] | None:
    """Recommend the single best player to drop: lowest-value bench player, over starters.

    `exclude_ids` protects specific players (e.g. just picked earlier in the
    same multi-round plan) from being recommended for drop in this pass.
    `ineligible_ids` (taxi/IR players) are never eligible to be assigned a
    starting slot here - Sleeper doesn't allow it - so they can't be wrongly
    protected from the drop pool as a false "starter"; they still land in
    `rows` and so can still be recommended for drop themselves.
    """
    rows = [r for r in player_value_rows(player_ids, players, fc_by_sleeper_id) if r["player_id"] not in exclude_ids]
    if not rows:
        return None

    eligible_rows = [r for r in rows if r["player_id"] not in ineligible_ids]
    assignments = assign_starters(eligible_rows, league["roster_positions"])
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


def hypothetical_needs_and_handcuffs(
    player_ids: list[str], players: dict[str, dict], handcuffs: dict[str, str]
) -> tuple[frozenset[str], dict[str, str]]:
    """Recompute need_positions and handcuff targets for a hypothetical (simulated) roster."""
    needs = need_positions(roster_needs_summary({"players": player_ids}, players))
    rb_ids = {pid for pid in player_ids if players.get(pid, {}).get("position") == "RB"}
    handcuff_targets = {
        backup_id: players.get(starter_id, {}).get("full_name", "")
        for starter_id, backup_id in handcuffs.items()
        if starter_id in rb_ids
    }
    return needs, handcuff_targets


def season_average_starter_value(
    player_ids: list[str],
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    byes: dict[str, int],
    league: dict,
    ineligible_ids: frozenset[str] = frozenset(),
) -> float:
    """Average optimal starting-lineup value across all 18 weeks, excluding bye'd players each week.

    This is the season-long analog of `lineup_breakdown`'s single snapshot.
    Every player misses exactly one week (their own bye), so this doesn't
    inherently favor or penalize any one player for having a bye at all —
    what it does capture is the *interaction*: a pickup whose bye lines up
    with an already-thin position contributes less across the season than
    the same value at a position with real depth behind it, and a pickup
    that specifically covers a weak spot during a bye week contributes
    more. Weekly-gap *detection* is handled separately (roster_weekly_gaps)
    — this is about getting the season-long value comparison right, not
    about re-deriving gap alerts.

    `ineligible_ids` (the roster's current taxi/IR players) never win a
    starting slot here regardless of value - Sleeper doesn't allow starting
    them. Doesn't attempt to model taxi/active transitions for newly
    simulated candidates mid-draft-plan - see PROJECT_PLAN.md.
    """
    rows = player_value_rows(player_ids, players, fc_by_sleeper_id)
    eligible_rows = [r for r in rows if r["player_id"] not in ineligible_ids]
    bye_by_player = {r["player_id"]: byes.get(players.get(r["player_id"], {}).get("team")) for r in eligible_rows}

    total = 0.0
    for week in NFL_WEEKS:
        week_rows = [r for r in eligible_rows if bye_by_player[r["player_id"]] != week]
        value_by_id = {r["player_id"]: r["adj_value"] or 0 for r in week_rows}
        assignments = assign_starters(week_rows, league["roster_positions"])
        total += sum(value_by_id.get(pid, 0) for _, pid in assignments if pid)

    return total / len(NFL_WEEKS)


def rank_by_marginal_value(
    candidate_ids: list[str],
    hypothetical_ids: list[str],
    players: dict[str, dict],
    fc_by_sleeper_id: dict[str, dict],
    byes: dict[str, int],
    league: dict,
    top_n: int = 3,
    exclude_from_drop: frozenset[str] = frozenset(),
    ineligible_ids: frozenset[str] = frozenset(),
    reserve_filled: int = 0,
) -> list[dict]:
    """Rank candidates by season-average marginal starting-lineup value, not raw trade value.

    For each candidate: simulate adding them (and, only if the roster is
    already at total capacity, making the resulting recommended drop), and
    measure how much the roster's season-average starting value (see
    season_average_starter_value) goes up. A drop is never forced just
    because a candidate was evaluated — a player added to genuinely open
    roster/taxi room (see roster_total_capacity) doesn't cost anything, so
    no drop is simulated and the marginal value isn't understated by an
    unnecessary cut. A modestly valued player at a genuinely weak position
    can beat a highly valued player who wouldn't even crack the starting
    lineup — this ranks by projected lineup impact, not market price. Bye
    weeks are already folded into the season average, not handled as a
    separate adjustment.

    `exclude_from_drop` protects specific players (e.g. picked in an
    earlier round of the same multi-round plan) from being recommended for
    drop here. `ineligible_ids` (the roster's current taxi/IR players) are
    never assignable to a starting slot in the simulation - passed through
    to both `season_average_starter_value` and `recommend_drop`.
    `reserve_filled` (the roster's actual current IR headcount, not the
    league's full `reserve_slots` setting - see `roster_total_capacity`)
    keeps a drafted rookie, who can never actually be assigned to reserve,
    from being treated as if empty IR slots were open room for them.
    Returns up to `top_n` entries (player_id, marginal_value, drop), sorted
    best first — the first is the recommended pick, the rest are backup
    options for the draft plan's alternates.
    """
    if not candidate_ids:
        return []

    total_capacity = roster_total_capacity(league, reserve_filled)
    baseline = season_average_starter_value(hypothetical_ids, players, fc_by_sleeper_id, byes, league, ineligible_ids)

    results = []
    for candidate_id in candidate_ids:
        with_candidate = hypothetical_ids + [candidate_id]
        if len(with_candidate) > total_capacity:
            drop = recommend_drop(
                with_candidate,
                players,
                fc_by_sleeper_id,
                league,
                exclude_ids=exclude_from_drop,
                ineligible_ids=ineligible_ids,
            )
        else:
            drop = None
        roster_after = [pid for pid in with_candidate if drop is None or pid != drop["player_id"]]
        after = season_average_starter_value(roster_after, players, fc_by_sleeper_id, byes, league, ineligible_ids)
        results.append({"player_id": candidate_id, "marginal_value": after - baseline, "drop": drop})

    results.sort(key=lambda r: r["marginal_value"], reverse=True)
    return results[:top_n]


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


def alternate_gap_note(
    candidate_id: str,
    drop: dict | None,
    hypothetical_ids: list[str],
    players: dict[str, dict],
    byes: dict[str, int],
    league: dict,
) -> str:
    """Describe what picking this specific alternate would change about weekly gaps, if anything.

    Compares against the hypothetical roster as it stood entering this
    round (not the plan's final roster), so the note reflects what THIS
    choice specifically does. Structured as a plain string so more note
    types (e.g. injury history, once/if that data is available) can be
    appended later without changing callers.
    """
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
) -> dict[str, Any]:
    """Plan for every pick the user owns this draft — what to pick and drop, and why.

    Ranks candidates by season-average MARGINAL starting-lineup value (see
    rank_by_marginal_value), not raw trade value — a modest player at a
    genuinely weak position can outrank a highly valued player who
    wouldn't even crack the starting lineup. Bye weeks are folded directly
    into that season average (season_average_starter_value), so a player
    isn't over- or under-weighted just because of when their bye falls.

    Rounds already played (`overall_pick < current_pick_no`) show the REAL
    player Sleeper recorded for that pick — scored the same marginal-value
    way retroactively, for a consistent "how much did this add" number —
    not a stale recommendation, so advancing rounds never hides what
    happened last round. Upcoming rounds are simulated: assumes "if these
    were your only remaining picks, back to back, on the board as it looks
    right now" — does NOT simulate the other ~11 teams' picks in between.
    Recomputed fresh on every refresh, so it stays accurate as the real
    draft progresses.

    A drop is still recommended for already-played rounds too (using the
    running hypothetical roster) since Sleeper has no record of whether a
    suggested drop was actually made — a live suggestion, not a confirmed
    transaction, labeled that way in the UI.

    Also returns up to 2 backup alternates per upcoming round
    (`alternates_by_pick`, keyed by overall_pick), each noting whether
    picking it instead would open a weekly gap the primary pick doesn't —
    a plain-string `notes` field meant to carry more note types later
    (e.g. injury history, if that data ever becomes available), not just
    this one.

    Finally compares the resulting hypothetical roster's weekly gaps
    against the current roster's (see roster_weekly_gaps), flagging any
    week where the full plan would introduce or worsen a dedicated-slot gap.
    """
    own_picks = sorted((p for p in ownership if p.owner_roster_id == user_roster_id), key=lambda p: p.overall_pick)

    available_ids = set(available.keys())
    hypothetical_ids = list(user_roster.get("players") or [])
    # The roster's current taxi/IR players are never eligible for a starting
    # slot in the simulation below - Sleeper doesn't allow it - regardless
    # of how their value compares to the rest of the roster.
    ineligible_ids = frozenset(user_roster.get("taxi") or []) | frozenset(user_roster.get("reserve") or [])
    # A drafted rookie can never actually be assigned to reserve/IR (that
    # requires a real injury designation) - only the roster's *actual*
    # current IR headcount should count toward total capacity, not the
    # league's full reserve_slots setting (see roster_total_capacity).
    # Reserve occupancy doesn't change across simulated rounds, since no
    # simulated pick ever lands on it, so this is computed once.
    reserve_filled = len(user_roster.get("reserve") or [])
    just_picked: set[str] = set()

    rounds = []
    alternates_by_pick: dict[int, pd.DataFrame] = {}

    for pick in own_picks:
        is_completed = pick.overall_pick < current_pick_no
        real_pick_id = real_picks_by_overall.get(pick.overall_pick)
        needs, handcuff_targets = hypothetical_needs_and_handcuffs(hypothetical_ids, players, handcuffs)

        if is_completed and real_pick_id:
            candidate_ids, top_n = [real_pick_id], 1
        else:
            candidate_ids, top_n = list(available_ids), 3

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
            }
        )

        if len(ranked) > 1:
            alt_rows = []
            for alt in ranked[1:]:
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

        available_ids.discard(picked_id)
        if drop:
            hypothetical_ids = [pid for pid in hypothetical_ids if pid != drop["player_id"]]
        hypothetical_ids.append(picked_id)
        just_picked.add(picked_id)

    hypothetical_roster = {"players": hypothetical_ids}
    alerts = gap_delta(user_roster, hypothetical_roster, players, byes, league)

    return {
        "rounds": pd.DataFrame(rounds),
        "alternates_by_pick": alternates_by_pick,
        "weekly_gap_alerts": alerts.reset_index(drop=True),
    }


def picks_until_turn(ownership: list[DraftPickSlot], user_roster_id: int, current_pick_no: int) -> int | None:
    """Return how many picks (by anyone) happen before the user's next pick.

    0 means it's the user's turn right now. None means the user has no
    more picks left in this draft.
    """
    next_pick = next(
        (p for p in ownership if p.owner_roster_id == user_roster_id and p.overall_pick >= current_pick_no),
        None,
    )
    return next_pick.overall_pick - current_pick_no if next_pick else None


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


def gather_state(
    league_id: str, username: str, force_full_refresh: bool, force_scoring_refresh: bool = False
) -> dict[str, Any]:
    """Pull one full snapshot of league + draft state and compute the big board.

    `force_scoring_refresh` is deliberately its own, separate flag - see the
    comment above the `player_scoring.get_multipliers` call below for why
    `force_full_refresh` alone never triggers it.
    """
    league = sleeper.get_league(league_id)
    rosters = sleeper.get_rosters(league_id)
    users = sleeper.get_users(league_id)
    draft = sleeper.get_draft(league["draft_id"])
    draft_picks = sleeper.get_draft_picks(league["draft_id"])
    traded_picks = sleeper.get_traded_picks(league_id)
    players = sleeper.get_players(force_refresh=force_full_refresh)

    num_qbs = league["roster_positions"].count("QB") + league["roster_positions"].count("SUPER_FLEX")
    num_teams = league["settings"]["num_teams"]
    ppr = league["scoring_settings"].get("rec", 0)
    fc_values = fantasycalc.get_dynasty_values(
        num_qbs=num_qbs, num_teams=num_teams, ppr=ppr, force_refresh=force_full_refresh
    )

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

    # The board itself shows the whole class, drafted or not (see build_big_board) -
    # only excludes rookies rostered outside this draft entirely (e.g. a pre-draft
    # waiver add), not ones taken here, which stay visible with attribution.
    pre_draft_rostered = rostered_player_ids(rosters) - picked_player_ids
    board_pool = {pid: info for pid, info in rookies.items() if pid not in pre_draft_rostered}
    draft_attribution = {
        p["player_id"]: (p["round"], team_names.get(p["roster_id"])) for p in draft_picks if p.get("player_id")
    }

    real_picks_by_overall = {
        p["pick_no"]: p["player_id"] for p in draft_picks if p.get("roster_id") == user_roster_id and p.get("player_id")
    }

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

    big_board = build_big_board(board_pool, fc_by_sleeper_id, needs, handcuff_targets, draft_attribution)
    roster_value = roster_value_analysis(user_roster, players, fc_by_sleeper_id, byes)
    lineup_starters, lineup_bench, lineup_taxi, lineup_ir = lineup_breakdown(user_roster, players, fc_by_sleeper_id, league)

    return {
        "league": league,
        "ownership": ownership,
        "current_pick_no": current_pick_no,
        "picks_until_turn": picks_until_turn(ownership, user_roster_id, current_pick_no),
        "your_picks": format_your_picks(ownership, user_roster_id, current_pick_no, team_names),
        "roster_needs": roster_needs,
        "need_positions": needs,
        "roster_capacity": roster_capacity(user_roster, league),
        "roster_value": roster_value,
        "roster_bye_conflicts": roster_bye_conflicts(user_roster, players, fc_by_sleeper_id, byes, league),
        "roster_weekly_gaps": roster_weekly_gaps(user_roster, players, byes, league),
        "roster_handcuffs": roster_handcuff_status(user_roster, players, handcuffs),
        "lineup_starters": lineup_starters,
        "lineup_bench": lineup_bench,
        "lineup_taxi": lineup_taxi,
        "lineup_ir": lineup_ir,
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
        ),
        "team_names": team_names,
        "data_warnings": data_warnings,
    }
