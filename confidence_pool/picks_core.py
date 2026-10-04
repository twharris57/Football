"""Confidence-pool picks: week detection, game selection, ranking, deadline, lock, scoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import nfl_data_py as nfl
import pandas as pd

ET = ZoneInfo("America/New_York")
SUNDAY_AFTERNOON_CUTOFF = "13:00"

# Stamped onto every pick. Bump it, and register a description in
# store.algorithm_versions, whenever the ranking math changes.
ALGORITHM_VERSION = "vig-proportional-v1"

# nfl_data_py's abbreviations (note: the Rams are "LA", not "LAR").
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
    """The season most relevant to `today`; January/February belong to last year's season."""
    return today.year if today.month >= 3 else today.year - 1


def current_week(schedule: pd.DataFrame, today: date) -> int:
    """The earliest regular-season week not fully played, else the final week."""
    reg = schedule[schedule["game_type"] == "REG"].copy()
    reg["gameday"] = pd.to_datetime(reg["gameday"]).dt.date
    last_day_by_week = reg.groupby("week")["gameday"].max().sort_index()
    upcoming = last_day_by_week[last_day_by_week >= today]
    if len(upcoming):
        return int(upcoming.index[0])
    return int(last_day_by_week.index[-1])


def week_date_labels(schedule: pd.DataFrame) -> dict[int, str]:
    """Map each regular-season week to its date span, e.g. `"Sep 13-14"`."""
    reg = schedule[schedule["game_type"] == "REG"].copy()
    reg["gameday"] = pd.to_datetime(reg["gameday"]).dt.date
    spans = reg.groupby("week")["gameday"].agg(["min", "max"])
    labels: dict[int, str] = {}
    for week, row in spans.iterrows():
        start, end = row["min"], row["max"]
        if start == end:
            labels[int(week)] = f"{start.strftime('%b')} {start.day}"
        elif start.month == end.month:
            labels[int(week)] = f"{start.strftime('%b')} {start.day}-{end.day}"
        else:
            labels[int(week)] = f"{start.strftime('%b')} {start.day}-{end.strftime('%b')} {end.day}"
    return labels


def _week_sunday(week_games: pd.DataFrame) -> date | None:
    """The date of this NFL week's Sunday, or `None` if the week has no games."""
    if week_games.empty:
        return None
    gamedays = pd.to_datetime(week_games["gameday"]).dt.date
    sunday_games = gamedays[week_games["weekday"] == "Sunday"]
    if not sunday_games.empty:
        return sunday_games.iloc[0]
    reference = gamedays.iloc[0]
    weekday_num = reference.weekday()  # Monday=0 ... Sunday=6
    if weekday_num in (0, 1):  # Monday/Tuesday belong to the preceding Sunday
        return reference - timedelta(days=weekday_num + 1)
    return reference + timedelta(days=6 - weekday_num)


def select_games(
    schedule: pd.DataFrame,
    year: int,
    week: int,
    selection_rule: str = "standard",
    sunday_afternoon_cutoff: str = SUNDAY_AFTERNOON_CUTOFF,
    configured_deadline: datetime | None = None,
) -> pd.DataFrame:
    """Apply the pool's game-selection rule (bylaws rule 14) for one week.

    - `'standard'`: kickoff from Sunday at `sunday_afternoon_cutoff` through Tuesday.
      Unknown kickoffs are excluded.
    - `'all_games'`: every game, or once `configured_deadline` is set, those kicking
      off at or after it. Unknown kickoffs are included.
    """
    week_games = schedule[
        (schedule["season"] == year)
        & (schedule["game_type"] == "REG")
        & (schedule["week"] == week)
    ]
    def _kickoffs() -> pd.Series:
        return pd.Series(
            [_try_kickoff_datetime(row["gameday"], row["gametime"]) for _, row in week_games.iterrows()],
            index=week_games.index,
        )

    if selection_rule == "all_games":
        if configured_deadline is None:
            selected = week_games
        else:
            kickoffs = _kickoffs()
            selected = week_games[kickoffs.isna() | (kickoffs >= configured_deadline)]
    else:
        sunday = _week_sunday(week_games)
        if sunday is None:
            selected = week_games
        else:
            window_start = kickoff_datetime(str(sunday), sunday_afternoon_cutoff)
            window_end = kickoff_datetime(str(sunday + timedelta(days=2)), "23:59")
            kickoffs = _kickoffs()
            selected = week_games[(kickoffs >= window_start) & (kickoffs <= window_end)]

    return selected[GAME_COLUMNS].reset_index(drop=True)


@dataclass(frozen=True)
class PickExplanation:
    """One game's raw and de-vigged probabilities and the resulting confidence."""

    home_moneyline: float
    away_moneyline: float
    home_prob_raw: float
    away_prob_raw: float
    home_prob: float
    away_prob: float
    confidence: float


def explain_odds(home_moneyline: float, away_moneyline: float) -> PickExplanation:
    """Convert one game's moneylines into a `PickExplanation`."""
    home_prob_raw = compute_probability(home_moneyline)
    away_prob_raw = compute_probability(away_moneyline)
    total = home_prob_raw + away_prob_raw
    if total > 0:
        home_prob = home_prob_raw / total
        away_prob = away_prob_raw / total
    else:
        home_prob, away_prob = home_prob_raw, away_prob_raw
    return PickExplanation(
        home_moneyline=home_moneyline,
        away_moneyline=away_moneyline,
        home_prob_raw=home_prob_raw,
        away_prob_raw=away_prob_raw,
        home_prob=home_prob,
        away_prob=away_prob,
        confidence=home_prob - away_prob,
    )


def rank_games(games: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rank games by confidence and assign N..1 points.

    Returns `(ranked, pending)`; `pending` holds games still missing a moneyline.
    """
    has_odds = games["home_moneyline"].notna() & games["away_moneyline"].notna()
    pending = games[~has_odds].reset_index(drop=True)

    rows = []
    for _, row in games[has_odds].iterrows():
        explanation = explain_odds(row["home_moneyline"], row["away_moneyline"])
        confidence = explanation.confidence
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
    """Add an `included` column from the checkbox map, defaulting to `True`.

    Persist the full result, not just included rows, or exclusions are lost on reload.
    """
    return auto_games.assign(
        included=auto_games["game_id"].map(included).fillna(True).astype(bool)
    )


def kickoff_datetime(gameday: str, gametime: str) -> datetime:
    """Combine schedule date/time strings into an ET datetime. Raises on a missing time."""
    return datetime.combine(
        pd.to_datetime(gameday).date(),
        datetime.strptime(gametime, "%H:%M").time(),
        tzinfo=ET,
    )


def _try_kickoff_datetime(gameday: str, gametime: str | None) -> datetime | None:
    """`kickoff_datetime`, or `None` when the kickoff time isn't finalized."""
    try:
        return kickoff_datetime(gameday, gametime)
    except (TypeError, ValueError):
        return None


def week_deadline(
    games: pd.DataFrame,
    configured_deadline: datetime | None = None,
) -> datetime:
    """Pick deadline (bylaws rule 2): `configured_deadline` if set, else the earliest known kickoff."""
    if configured_deadline is not None:
        return configured_deadline

    kickoffs = [
        _try_kickoff_datetime(row["gameday"], row["gametime"]) for _, row in games.iterrows()
    ]
    known_kickoffs = [k for k in kickoffs if k is not None]
    if not known_kickoffs:
        raise ValueError(
            "Cannot compute a deadline: no selected games have a known kickoff time yet"
        )
    return min(known_kickoffs)


def is_locked(now: datetime, deadline: datetime) -> bool:
    """Whether a week's pick-submission deadline has passed."""
    return now >= deadline


# A save counts as a week's "first look" only within this many days before its
# earliest kickoff (so browsing ahead doesn't count) ...
FIRST_LOOK_WINDOW_DAYS = 3

# ... or this many days after (a Monday check-in on Sunday's games).
FIRST_LOOK_LATE_GRACE_DAYS = 1


def is_first_look_window(games: pd.DataFrame, now: datetime) -> bool:
    """Whether a save at `now` may claim the week's `'first'` snapshot."""
    kickoffs = [
        _try_kickoff_datetime(row["gameday"], row["gametime"]) for _, row in games.iterrows()
    ]
    known_kickoffs = [k for k in kickoffs if k is not None]
    if not known_kickoffs:
        return False
    earliest_kickoff = min(known_kickoffs)
    days_until_kickoff = (earliest_kickoff.date() - now.date()).days
    return -FIRST_LOOK_LATE_GRACE_DAYS <= days_until_kickoff <= FIRST_LOOK_WINDOW_DAYS


@dataclass(frozen=True)
class LockOutcome:
    """What to persist when a week's deadline passes. Pass every field to `store.save_week()`."""

    locked: bool
    games: pd.DataFrame
    picks: pd.DataFrame
    warning: str | None
    generated_at: datetime | None
    first_snapshot_eligible: bool = False


def resolve_week_lock(
    auto_games: pd.DataFrame,
    included: dict[str, bool],
    saved_games: pd.DataFrame,
    saved_picks: pd.DataFrame,
    now: datetime,
) -> LockOutcome:
    """Decide what to lock for a week whose deadline has passed.

    - Saved picks exist: lock them as-is, with their original timestamp.
    - Otherwise compute from current odds, warning if any included game already started.
    - Odds still missing: don't lock; warn (and name any game already started).

    A lock never claims the `'first'` snapshot — nothing can follow it to compare against.
    """
    if not saved_picks.empty:
        original_generated_at = datetime.fromisoformat(saved_games["captured_at"].iloc[0])
        return LockOutcome(
            locked=True, games=saved_games, picks=saved_picks, warning=None,
            generated_at=original_generated_at,
        )

    games_all = games_with_included_flags(auto_games, included)
    included_games = games_all[games_all["included"]]
    started = [
        (row["away_team"], row["home_team"])
        for _, row in included_games.iterrows()
        if (kickoff := _try_kickoff_datetime(row["gameday"], row["gametime"])) is not None
        and kickoff <= now
    ]
    started_matchups = ", ".join(f"{away} @ {home}" for away, home in started)

    ranked, pending = rank_games(included_games)
    if not pending.empty:
        missing = ", ".join(
            f"{r['away_team']} @ {r['home_team']}" for _, r in pending.iterrows()
        )
        warning = (
            f"Pick deadline has passed, but odds aren't posted yet for: {missing}. "
            "Picks have not been locked -- reload once odds are posted."
        )
        if started:
            warning += (
                f" Kickoff has already passed for: {started_matchups} -- if its "
                "odds never post, this week will need manual review rather than "
                "waiting indefinitely for a reload to unblock it."
            )
        return LockOutcome(
            locked=False, games=pd.DataFrame(), picks=pd.DataFrame(), warning=warning,
            generated_at=None,
        )

    warning = None
    if started:
        warning = (
            "No picks were ever generated for this week before the deadline, "
            f"and kickoff has already passed for: {started_matchups}. Locked "
            "using odds computed just now -- these may no longer reflect the "
            "original pregame line."
        )
    return LockOutcome(locked=True, games=games_all, picks=ranked, warning=warning, generated_at=now)


def check_actual_picks(
    entries: dict[str, tuple[str | None, int | None]],
    team_names: dict[str, str] | None = None,
    late: bool = False,
) -> list[str]:
    """Explain bylaws-defined irregularities in a submitted card; never blocks a save.

    Covers late cards (rule 2), unmarked winners (16), blank points (15), and duplicate
    points (7). `entries` maps `game_id -> (winner, points)`, with `None` for blank.
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


@dataclass(frozen=True)
class PickResult:
    """One game's score. `points_awarded` can differ from `correct * points` (rule 7)."""

    game_id: str
    predicted_winner: str | None
    points: int | None
    actual_winner: str | None
    decided: bool
    correct: bool
    points_awarded: int


@dataclass(frozen=True)
class WeekScore:
    """A week's score; provisional while `games_decided < games_total`."""

    total_points: int
    games_decided: int
    games_total: int
    results: list[PickResult]


def week_phase(week_score: WeekScore) -> str:
    """Where a locked week stands: `'picks'` (no game final), `'in_progress'`, or `'final'`."""
    if week_score.games_decided == 0:
        return "picks"
    if week_score.games_decided < week_score.games_total:
        return "in_progress"
    return "final"


def score_picks(
    entries: dict[str, tuple[str | None, int | None]], outcomes: pd.DataFrame
) -> WeekScore:
    """Score `game_id -> (winner, points)` picks against `store.get_game_outcomes()`.

    Ties score nothing (rule 6). A shared points value is credited once if any of
    its games was correct (rule 7). Undecided games count toward `games_total` only.
    """
    outcomes_by_id = {row["game_id"]: row for _, row in outcomes.iterrows()}

    rows = []
    for game_id, (winner, points) in entries.items():
        outcome = outcomes_by_id.get(game_id)
        decided = (
            outcome is not None
            and pd.notna(outcome["home_score"])
            and pd.notna(outcome["away_score"])
        )
        actual_winner = None
        if decided and outcome["home_score"] != outcome["away_score"]:
            actual_winner = (
                outcome["home_team"]
                if outcome["home_score"] > outcome["away_score"]
                else outcome["away_team"]
            )
        correct = decided and actual_winner is not None and winner == actual_winner
        rows.append(
            {
                "game_id": game_id,
                "predicted_winner": winner,
                "points": points,
                "actual_winner": actual_winner,
                "decided": decided,
                "correct": correct,
            }
        )

    by_points: dict[int, list[int]] = {}
    for i, row in enumerate(rows):
        if row["points"] is not None:
            by_points.setdefault(row["points"], []).append(i)

    points_awarded = [0] * len(rows)
    for points, idxs in by_points.items():
        correct_idxs = [i for i in idxs if rows[i]["correct"]]
        if correct_idxs:
            points_awarded[correct_idxs[0]] = points

    results = [
        PickResult(
            game_id=row["game_id"],
            predicted_winner=row["predicted_winner"],
            points=row["points"],
            actual_winner=row["actual_winner"],
            decided=row["decided"],
            correct=row["correct"],
            points_awarded=points_awarded[i],
        )
        for i, row in enumerate(rows)
    ]
    return WeekScore(
        total_points=sum(points_awarded),
        games_decided=sum(1 for row in rows if row["decided"]),
        games_total=len(rows),
        results=results,
    )


def check_reported_score(
    week_score: WeekScore, reported_score: int | None, late: bool
) -> str | None:
    """A mismatch message if the reported score disagrees with ours, else `None`.

    Skipped when nothing's reported, the week isn't fully decided, or the card was
    late (rule 2's penalty needs other entrants' scores).
    """
    if reported_score is None:
        return None
    if week_score.games_decided < week_score.games_total:
        return None
    if late:
        return None
    if reported_score != week_score.total_points:
        return (
            f"Reported score ({reported_score}) doesn't match this app's computed "
            f"score ({week_score.total_points}) -- worth double-checking against the "
            "pool sheet."
        )
    return None
