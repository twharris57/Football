"""Core confidence-pool picks logic: current-week detection, the Legion
pool's game-selection rules, Vegas-odds ranking, and the pick-submission
deadline.

This is a fresh library, not a refactor of `football_enhanced.py` (which
stays untouched as the proven, standalone reference implementation this
reuses the math from) -- see `docs/confidence-pool-web-app.md` for the
full game-selection rules and why they're shaped this way.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import nfl_data_py as nfl
import pandas as pd

ET = ZoneInfo("America/New_York")
SUNDAY_AFTERNOON_CUTOFF = "13:00"
LATE_SEASON_WEEKS = (17, 18)

# The 32 team abbreviations nfl_data_py's schedule data actually uses (verified
# against a real fetch, not guessed -- notably the Rams are "LA", not "LAR"). Lets
# the Settings tab offer every team for a display-name override (see
# `store.DEFAULT_TEAM_DISPLAY_NAMES`) even before it's appeared in a fetched
# schedule this session. Stable, but not permanent -- update by hand if a team
# relocates or rebrands (rare; e.g. WAS's 2022 renaming).
NFL_TEAM_ABBREVIATIONS = [
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
    "DET", "GB", "HOU", "IND", "JAX", "KC", "LA", "LAC", "LV", "MIA",
    "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB",
    "TEN", "WAS",
]

GAME_COLUMNS = [
    "game_id",
    "home_team",
    "away_team",
    "home_moneyline",
    "away_moneyline",
    "gameday",
    "weekday",
    "gametime",
]


def compute_probability(moneyline: float) -> float:
    """Convert an American moneyline to an implied win probability."""
    if moneyline > 0:
        return 100 / (moneyline + 100)
    return abs(moneyline) / (abs(moneyline) + 100)


def get_schedule(year: int) -> pd.DataFrame:
    """Fetch the full schedule (all game types) for one season."""
    return nfl.import_schedules(years=[year])


def default_season_year(today: date) -> int:
    """The NFL season year most relevant to `today`.

    nfl_data_py's `season` column is the year a season *started* in, even
    for games played into the following January/February. Treat March
    through December as "the season starting this calendar year" (correct
    in-season, and a reasonable default in the summer before it starts);
    January/February default to the previous calendar year's season, which
    is still in its playoffs.
    """
    return today.year if today.month >= 3 else today.year - 1


def current_week(schedule: pd.DataFrame, today: date) -> int:
    """The earliest regular-season week whose games haven't all been played
    as of `today`; falls back to the season's final week once they have.
    """
    reg = schedule[schedule["game_type"] == "REG"].copy()
    reg["gameday"] = pd.to_datetime(reg["gameday"]).dt.date
    last_day_by_week = reg.groupby("week")["gameday"].max().sort_index()
    upcoming = last_day_by_week[last_day_by_week >= today]
    if len(upcoming):
        return int(upcoming.index[0])
    return int(last_day_by_week.index[-1])


def select_games(schedule: pd.DataFrame, year: int, week: int) -> pd.DataFrame:
    """Apply the Legion pool's game-selection rules (bylaws rule 14) for one
    week: regular season only, Sunday-afternoon (kickoff >= 1pm ET) and
    Monday-night games for weeks 1-16, Saturday games only for weeks 17-18.
    """
    week_games = schedule[
        (schedule["season"] == year)
        & (schedule["game_type"] == "REG")
        & (schedule["week"] == week)
    ]

    if week in LATE_SEASON_WEEKS:
        selected = week_games[week_games["weekday"] == "Saturday"]
    else:
        is_monday = week_games["weekday"] == "Monday"
        is_sunday_afternoon = (week_games["weekday"] == "Sunday") & (
            week_games["gametime"] >= SUNDAY_AFTERNOON_CUTOFF
        )
        selected = week_games[is_monday | is_sunday_afternoon]

    return selected[GAME_COLUMNS].reset_index(drop=True)


def rank_games(games: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rank games by Vegas-odds confidence and assign N..1 points, descending.

    Returns `(ranked, pending)` -- `pending` holds any game missing a
    moneyline (odds not posted yet), kept separate rather than ranked, since
    the confidence math can't run on NaN without silently producing NaN
    comparisons downstream (see `valuation_principles.md`'s NaN-handling rule).
    """
    has_odds = games["home_moneyline"].notna() & games["away_moneyline"].notna()
    pending = games[~has_odds].reset_index(drop=True)

    rows = []
    for _, row in games[has_odds].iterrows():
        home_prob = compute_probability(row["home_moneyline"])
        away_prob = compute_probability(row["away_moneyline"])
        total = home_prob + away_prob
        if total > 0:
            home_prob /= total
            away_prob /= total
        confidence = home_prob - away_prob
        predicted_winner = row["home_team"] if confidence > 0 else row["away_team"]
        rows.append(
            {
                "game_id": row["game_id"],
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "predicted_winner": predicted_winner,
                "confidence": confidence,
            }
        )

    ranked = pd.DataFrame(
        rows, columns=["game_id", "home_team", "away_team", "predicted_winner", "confidence"]
    )
    ranked = ranked.sort_values(
        "confidence", key=lambda s: s.abs(), ascending=False
    ).reset_index(drop=True)
    ranked.insert(0, "points", range(len(ranked), 0, -1))
    return ranked, pending


def games_with_included_flags(
    auto_games: pd.DataFrame, included: dict[str, bool]
) -> pd.DataFrame:
    """Attach a real `included` column to every auto-selected game, from the
    per-game checkbox state (`included`) -- defaulting to `True` for any
    game not present in the map (nothing has excluded it yet).

    Callers must persist the *full* result via `store.save_week`, not just
    the included subset -- saving only the included games silently drops a
    user's exclusion the moment the week is next loaded (its `game_id`
    would simply be absent from `included`, defaulting back to `True`).
    """
    return auto_games.assign(
        included=auto_games["game_id"].map(included).fillna(True).astype(bool)
    )


def kickoff_datetime(gameday: str, gametime: str) -> datetime:
    """Combine a schedule row's date/time strings into an ET-aware datetime."""
    return datetime.combine(
        pd.to_datetime(gameday).date(),
        datetime.strptime(gametime, "%H:%M").time(),
        tzinfo=ET,
    )


def week_deadline(
    games: pd.DataFrame,
    week: int,
    configured_deadline: datetime | None = None,
) -> datetime:
    """The pick-submission cutoff for a week's selected games (bylaws rule 2).

    Weeks 1-16: the earliest kickoff among the selected games -- picks are
    due "before kick-off". Weeks 17-18: the bylaws set an explicit early
    cutoff (earlier than any of that week's kickoffs) that the commissioner
    announces each year, so it comes from `configured_deadline`
    (`season_config`) rather than being computed -- falling back to the
    earliest Saturday kickoff if it hasn't been configured yet.
    """
    kickoffs = [
        kickoff_datetime(row["gameday"], row["gametime"]) for _, row in games.iterrows()
    ]
    if not kickoffs:
        raise ValueError("Cannot compute a deadline with no selected games")
    earliest_kickoff = min(kickoffs)

    if week in LATE_SEASON_WEEKS and configured_deadline is not None:
        return configured_deadline
    return earliest_kickoff


def is_locked(now: datetime, deadline: datetime) -> bool:
    """Whether a week's pick-submission deadline has passed."""
    return now >= deadline


@dataclass(frozen=True)
class LockOutcome:
    """What to do about a week whose deadline has just passed and isn't
    locked yet, from `resolve_week_lock`."""

    locked: bool
    games: pd.DataFrame
    picks: pd.DataFrame
    warning: str | None


def resolve_week_lock(
    auto_games: pd.DataFrame,
    included: dict[str, bool],
    saved_games: pd.DataFrame,
    saved_picks: pd.DataFrame,
) -> LockOutcome:
    """Decide what to lock in for a week whose deadline has just passed.

    Prefers the last manually-generated snapshot (`saved_picks`) so the
    locked historical record matches what was actually reviewed and
    submitted, rather than recomputing against whatever odds happen to be
    live at the moment the lock is evaluated -- moneylines move over the
    course of a week, so recomputing here could silently lock in different
    picks than the ones actually generated and acted on earlier.

    Only computes a fresh snapshot from `auto_games` if nothing was ever
    generated for the week. If odds are still pending for a selected game
    and there's no prior snapshot to fall back to, returns `locked=False`
    with an explanatory `warning` instead of locking nothing silently.
    """
    if not saved_picks.empty:
        return LockOutcome(locked=True, games=saved_games, picks=saved_picks, warning=None)

    games_all = games_with_included_flags(auto_games, included)
    ranked, pending = rank_games(games_all[games_all["included"]])
    if not pending.empty:
        missing = ", ".join(
            f"{r['away_team']} @ {r['home_team']}" for _, r in pending.iterrows()
        )
        warning = (
            f"Pick deadline has passed, but odds aren't posted yet for: {missing}. "
            "Picks have not been locked -- reload once odds are posted."
        )
        return LockOutcome(locked=False, games=pd.DataFrame(), picks=pd.DataFrame(), warning=warning)
    return LockOutcome(locked=True, games=games_all, picks=ranked, warning=None)
