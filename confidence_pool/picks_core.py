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

# Stamped onto every generated pick (see rank_games()) so a future methodology
# change (CP-12) can tell exactly which formula produced a historical row.
# Bump this string -- and add a row to store.py's algorithm_versions table
# describing the change -- whenever this module's ranking math changes.
ALGORITHM_VERSION = "vig-proportional-v1"

# The 32 team abbreviations nfl_data_py's schedule data actually uses (verified
# against a real fetch, not guessed -- notably the Rams are "LA", not "LAR"). Lets
# the Settings tab offer every team for a display-name override (see
# `store.DEFAULT_TEAMS`) even before it's appeared in a fetched schedule this
# session. Stable, but not permanent -- update by hand if a team relocates or
# rebrands (rare; e.g. WAS's 2022 renaming).
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


def select_games(
    schedule: pd.DataFrame,
    year: int,
    week: int,
    selection_rule: str = "standard",
    sunday_afternoon_cutoff: str = SUNDAY_AFTERNOON_CUTOFF,
) -> pd.DataFrame:
    """Apply the Legion pool's game-selection rules (bylaws rule 14) for one
    week.

    `selection_rule` (from `store.season_week_rules` -- only weeks whose
    rule differs from the default get a row there, e.g. weeks 17-18):

    - `'standard'` (the default): regular season only, Sunday-afternoon
      (kickoff >= `sunday_afternoon_cutoff`) and Monday-night games. This
      filter exists so the deadline (the earliest *selected* kickoff)
      can't fall after an excluded early game (Thursday, an early-Sunday
      international game) has already been decided, which would leak
      information before picks are due.
    - `'all_games'`: every game that week, no weekday filter. Used where
      the deadline is a single early cutoff *before all* of that week's
      kickoffs (see `week_deadline()`) rather than "before the earliest
      selected kickoff" -- the leak `'standard'` guards against can't
      happen regardless of weekday, so nothing needs excluding. Confirmed
      against real 2025-season results: week 18's sheet included a
      Saturday game (Jan 3) alongside the Sunday slate (Jan 4), which a
      Sunday/Monday-only filter would have excluded.
    """
    week_games = schedule[
        (schedule["season"] == year)
        & (schedule["game_type"] == "REG")
        & (schedule["week"] == week)
    ]

    if selection_rule == "all_games":
        selected = week_games
    else:
        is_monday = week_games["weekday"] == "Monday"
        is_sunday_afternoon = (week_games["weekday"] == "Sunday") & (
            week_games["gametime"] >= sunday_afternoon_cutoff
        )
        selected = week_games[is_monday | is_sunday_afternoon]

    return selected[GAME_COLUMNS].reset_index(drop=True)


def rank_games(games: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rank games by Vegas-odds confidence and assign N..1 points, descending.

    Returns `(ranked, pending)` -- `pending` holds any game missing a
    moneyline (odds not posted yet), kept separate rather than ranked, since
    the confidence math can't run on NaN without silently producing NaN
    comparisons downstream (see `valuation_principles.md`'s NaN-handling rule).

    `ranked` carries an `algorithm_version` column (`ALGORITHM_VERSION`) on
    every row -- callers persist it as-is rather than stamping it on
    separately, so a pick's provenance travels with it even when a stored
    snapshot is later reused verbatim (see `resolve_week_lock()`).
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
    ranked["algorithm_version"] = ALGORITHM_VERSION
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
    configured_deadline: datetime | None = None,
) -> datetime:
    """The pick-submission cutoff for a week's selected games (bylaws rule 2).

    Uses `configured_deadline` if given -- an explicit early cutoff from
    `store.season_week_rules` (commissioner-announced each year for weeks
    like 17-18, where the deadline sits before all of that week's kickoffs
    rather than the earliest selected one). Otherwise falls back to the
    earliest kickoff among the selected games -- picks are due "before
    kick-off". The caller decides whether a configured override applies
    (by looking up `season_week_rules` for this week), not this function.
    """
    kickoffs = [
        kickoff_datetime(row["gameday"], row["gametime"]) for _, row in games.iterrows()
    ]
    if not kickoffs:
        raise ValueError("Cannot compute a deadline with no selected games")
    earliest_kickoff = min(kickoffs)

    if configured_deadline is not None:
        return configured_deadline
    return earliest_kickoff


def is_locked(now: datetime, deadline: datetime) -> bool:
    """Whether a week's pick-submission deadline has passed."""
    return now >= deadline


# How close to a week's earliest kickoff a save has to be to count as a
# real first look at that week, not a click-ahead preview of a future one.
# Matches the actual usage pattern -- check a few days before kickoff
# (Thursday/Friday, maybe re-check Saturday morning), not however many
# weeks in advance the season/week selector happens to let you browse to.
FIRST_LOOK_WINDOW_DAYS = 3


def is_first_look_window(games: pd.DataFrame, now: datetime) -> bool:
    """Whether `now` is within `FIRST_LOOK_WINDOW_DAYS` of this week's
    earliest kickoff -- used to decide whether a save is eligible to become
    that week's immutable `'first'` snapshot (see `store.save_week`).
    Comparing whole calendar days, not exact hours, since "Thursday" vs.
    "the following Wednesday" is the distinction that actually matters here.
    """
    kickoffs = [
        kickoff_datetime(row["gameday"], row["gametime"]) for _, row in games.iterrows()
    ]
    if not kickoffs:
        return False
    earliest_kickoff = min(kickoffs)
    return (earliest_kickoff.date() - now.date()).days <= FIRST_LOOK_WINDOW_DAYS


@dataclass(frozen=True)
class LockOutcome:
    """What to do about a week whose deadline has just passed and isn't
    locked yet, from `resolve_week_lock`."""

    locked: bool
    games: pd.DataFrame
    picks: pd.DataFrame
    warning: str | None
    generated_at: datetime | None


def resolve_week_lock(
    auto_games: pd.DataFrame,
    included: dict[str, bool],
    saved_games: pd.DataFrame,
    saved_picks: pd.DataFrame,
    now: datetime,
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

    The returned `generated_at` is what the caller should persist as this
    save's timestamp -- the *reused* snapshot's own original `captured_at`
    (from `saved_games`) when locking in prior data verbatim, not `now`.
    Reusing a snapshot's values but stamping the lock-evaluation moment
    onto them would overwrite the true generation time the `'first'`/
    `'current'` snapshot split exists to preserve.
    """
    if not saved_picks.empty:
        original_generated_at = datetime.fromisoformat(saved_games["captured_at"].iloc[0])
        return LockOutcome(
            locked=True, games=saved_games, picks=saved_picks, warning=None,
            generated_at=original_generated_at,
        )

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
        return LockOutcome(
            locked=False, games=pd.DataFrame(), picks=pd.DataFrame(), warning=warning,
            generated_at=None,
        )
    return LockOutcome(locked=True, games=games_all, picks=ranked, warning=None, generated_at=now)


def check_actual_picks(
    entries: dict[str, tuple[str | None, int | None]],
    team_names: dict[str, str] | None = None,
    late: bool = False,
) -> list[str]:
    """Check an actual-submission entry (`game_id -> (predicted_winner,
    points)`, `None` meaning left blank) for the real-world irregularities
    the Legion pool bylaws themselves define a resolution for -- none of
    which invalidate the submission, so this never blocks a save, only
    explains what the bylaws say happens:

    - Rule 2: the card was submitted late -- docked 10 points below that
      week's lowest card (needs the field's actual scores to compute; see
      `CP-3`/the eventual `weekly_standings` -- this only flags the fact).
    - Rule 16: an unmarked winning team -- that game's points are lost.
    - Rule 15: a blank points box -- that number's points are lost.
    - Rule 7: two games sharing the same points value -- the *lower*
      value is the one that counts, whichever of the two (or both) was
      correct.

    (Rule 8's "forwarded to the rules committee" is the actual
    invalidation path, for illegible paper cards -- not applicable to an
    app-entered submission, which is always legible.)

    Returns a human-readable issue per irregularity found, empty if the
    submission is a clean `1..N` permutation with every game marked and
    was not late. `team_names` is used only to make a message read
    naturally; falls back to the raw abbreviation/game_id if omitted.
    """
    names = team_names or {}
    points_seen: dict[int, str] = {}
    issues: list[str] = []
    if late:
        issues.append(
            "Card submitted late -- bylaws rule 2, docked 10 points below this "
            "week's lowest card (not excluded)."
        )
    for game_id, (winner, points) in entries.items():
        label = names.get(game_id, game_id)
        if winner is None:
            issues.append(
                f"{label}: no winner marked -- bylaws rule 16, that game's points are lost."
            )
        if points is None:
            issues.append(
                f"{label}: no points assigned -- bylaws rule 15, that point value is lost."
            )
        elif points in points_seen:
            other = names.get(points_seen[points], points_seen[points])
            issues.append(
                f"{label} and {other} both used {points} points -- bylaws rule 7, only the "
                "lower value counts (for whichever game was correct, or either if both were)."
            )
        else:
            points_seen[points] = game_id
    return issues
