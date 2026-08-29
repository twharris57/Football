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
from datetime import date, datetime, time, timedelta
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


def week_date_labels(schedule: pd.DataFrame) -> dict[int, str]:
    """Map each of `schedule`'s regular-season weeks to a human date span
    (e.g. `"Sep 13-14"`), for labeling a week selector -- so a bare week
    number isn't the only way to tell what part of the calendar it covers.
    """
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
    """The calendar date of this NFL week's Sunday -- the anchor for
    `select_games()`'s standard-week selection window.

    Prefers a real Sunday game's own date when one exists (true for the
    overwhelming majority of weeks); otherwise rolls any other game's date
    to that week's Sunday, since an NFL week runs Thursday through the
    following Monday/Tuesday with exactly one Sunday in between. `None` if
    there are no games to anchor from (bye week / invalid week number).
    """
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
    """Apply the Legion pool's game-selection rules (bylaws rule 14) for one
    week.

    `selection_rule` (from `store.season_week_rules` -- only weeks whose
    rule differs from the default get a row there, e.g. weeks 16-18):

    - `'standard'` (the default): a game is selected if its kickoff falls
      in the window from this week's Sunday at `sunday_afternoon_cutoff`
      through the following Tuesday end-of-day. In practice that's
      Sunday-afternoon and Monday-night games, but as a real datetime
      comparison rather than a fixed weekday enumeration, it also catches
      a rare Tuesday makeup game (a weather postponement has happened at
      least once in NFL history) that a Monday/Sunday-only check would
      silently miss. This window exists so the deadline (the earliest
      *selected* kickoff) can't fall after an excluded early game
      (Thursday, an early-Sunday international game) has already been
      decided, which would leak information before picks are due.
    - `'all_games'`: every game that week, if `configured_deadline` isn't
      known yet -- there's nothing yet to compare kickoffs against, so
      `'standard'`'s no-leak concern can't be evaluated either way. Once a
      deadline is configured, only games kicking off at or after it count,
      on the same reasoning as `'standard'`'s window, rather than assuming
      the override always predates every kickoff that week. Used where the
      deadline is a single early cutoff *before all* of that week's
      kickoffs (see `week_deadline()`). Confirmed against real 2025-season
      results: week 18's sheet included a Saturday game (Jan 3) alongside
      the Sunday slate (Jan 4), which a Sunday/Monday-only filter would
      have excluded.

    A game whose `gametime` isn't finalized yet in the schedule data is
    never a crash (CP-35), but the two rules resolve "unknown" oppositely,
    matching what each one's own no-leak guarantee actually needs:
    `'standard'` excludes it (an unverifiable window match defaults to
    "don't leak, don't include"), while `'all_games'` includes it (its
    deadline is documented to predate every real kickoff that week
    regardless, so an unknown time isn't evidence for dropping a real game
    off the sheet).
    """
    week_games = schedule[
        (schedule["season"] == year)
        & (schedule["game_type"] == "REG")
        & (schedule["week"] == week)
    ]
    def _kickoffs() -> pd.Series:
        # A per-game unknown kickoff (nfl_data_py has no guarantee every
        # game's gametime is finalized yet -- most likely for a
        # late-season, flex-scheduling-eligible game) must not crash the
        # whole week's comparison -- _try_kickoff_datetime returns None
        # for that game instead of raising (CP-35).
        return pd.Series(
            [_try_kickoff_datetime(row["gameday"], row["gametime"]) for _, row in week_games.iterrows()],
            index=week_games.index,
        )

    if selection_rule == "all_games":
        if configured_deadline is None:
            selected = week_games
        else:
            kickoffs = _kickoffs()
            # An unknown kickoff is presumed to belong, not excluded: this
            # rule's own deadline is documented to predate every real
            # kickoff that week (see docs/confidence-pool-web-app.md), so
            # "we don't know the exact time yet" is not evidence a game
            # should be dropped from the sheet -- only a *known* kickoff
            # before the deadline is.
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
    """The intermediate math behind one game's confidence score -- the raw
    (pre-de-vig) implied probability from each side's moneyline, the
    de-vigged probabilities actually used for ranking, and the resulting
    confidence. Exposed so the UI can show a pick's real inputs and
    working, not just the final points/confidence columns."""

    home_moneyline: float
    away_moneyline: float
    home_prob_raw: float
    away_prob_raw: float
    home_prob: float
    away_prob: float
    confidence: float


def explain_odds(home_moneyline: float, away_moneyline: float) -> PickExplanation:
    """Convert one game's moneylines into a `PickExplanation`.

    `rank_games` calls this for its own confidence score rather than
    reimplementing the math inline, so the ranking and the UI's
    per-pick detail view can never drift apart (see
    `valuation_principles.md`'s "one valuation strategy" rule, mirrored
    here for the confidence-pool side).
    """
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
    """Combine a schedule row's date/time strings into an ET-aware datetime.

    Raises if `gametime` isn't a parseable "HH:MM" string -- nfl_data_py
    doesn't guarantee one is set yet for a game whose kickoff hasn't been
    finalized (most often a late-season, flex-scheduling-eligible game).
    Callers comparing kickoffs across a whole week, where one game's
    unknown time shouldn't crash the rest, should use
    `_try_kickoff_datetime` instead.
    """
    return datetime.combine(
        pd.to_datetime(gameday).date(),
        datetime.strptime(gametime, "%H:%M").time(),
        tzinfo=ET,
    )


def _try_kickoff_datetime(gameday: str, gametime: str | None) -> datetime | None:
    """`kickoff_datetime`, tolerant of a not-yet-finalized `gametime` --
    `None` instead of raising, so one game's unknown kickoff doesn't crash
    a comparison across its whole week (CP-35). A `None` result means
    "kickoff unknown," never "kicks off at the start of time": it compares
    as `False` against any window/deadline check (a `None`/`NaT` value is
    never `>=` or `<=` anything), so it naturally excludes itself from a
    selection window rather than falsely matching one.
    """
    try:
        return kickoff_datetime(gameday, gametime)
    except (TypeError, ValueError):
        return None


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

    Never parses a kickoff when `configured_deadline` already answers the
    question (CP-35) -- `games` can still include a game whose kickoff
    isn't finalized yet (`select_games`'s `'all_games'` rule lets one
    through deliberately, see its docstring), and that game's unknown
    gametime has no bearing on an already-known configured deadline. When
    no override is given, a game with an unknown kickoff is excluded from
    the earliest-kickoff computation rather than crashing it.
    """
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

    A game with an unfinalized kickoff (CP-35) is excluded from the
    earliest-kickoff computation rather than crashing it; `False` if that
    leaves no known kickoff to compare against, same as the "no games at
    all" case -- there's nothing yet to call a first look at.
    """
    kickoffs = [
        _try_kickoff_datetime(row["gameday"], row["gametime"]) for _, row in games.iterrows()
    ]
    known_kickoffs = [k for k in kickoffs if k is not None]
    if not known_kickoffs:
        return False
    earliest_kickoff = min(known_kickoffs)
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

    If that fresh computation happens after kickoff for one of the
    included games -- the app was never opened for this week until well
    after its deadline, possibly after games have already started or
    finished -- `warning` flags which games, since their moneylines
    may no longer reflect the original pregame line. Still locks in the
    computed result rather than refusing to lock at all: there's no better
    data to fall back to, and leaving the week unresolved forever would be
    worse than locking with a caveat. This can't happen on the preferred,
    prior-snapshot path above, since that path never recomputes odds. An
    included game with an unfinalized kickoff (CP-35) is treated as "not
    yet started" for this warning rather than crashing on it -- there's no
    way to confirm it started without a known kickoff time.

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

    included_games = games_all[games_all["included"]]
    started = [
        (row["away_team"], row["home_team"])
        for _, row in included_games.iterrows()
        if (kickoff := _try_kickoff_datetime(row["gameday"], row["gametime"])) is not None
        and kickoff <= now
    ]
    warning = None
    if started:
        matchups = ", ".join(f"{away} @ {home}" for away, home in started)
        warning = (
            "No picks were ever generated for this week before the deadline, "
            f"and kickoff has already passed for: {matchups}. Locked using "
            "odds computed just now -- these may no longer reflect the "
            "original pregame line."
        )
    return LockOutcome(locked=True, games=games_all, picks=ranked, warning=warning, generated_at=now)


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
      week's lowest card. Not computable here (needs every other pool
      entrant's score, which this app never tracks) -- this only flags the
      fact; `store.set_reported_score()`/`check_reported_score()` are
      where the pool's own officially reported score gets recorded and
      cross-checked instead, once posted.
    - Rule 16: an unmarked winning team -- that game's points are lost.
    - Rule 15: a blank points box -- that number's points are lost.
    - Rule 7: two games sharing the same points value -- the *lower*
      value is the one that counts, whichever of the two (or both) was
      correct. Resolved for real (not just flagged) by `score_picks()`.

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


@dataclass(frozen=True)
class PickResult:
    """One game's contribution to a `WeekScore` -- `correct` is the bare
    fact of whether the pick matched the outcome; `points_awarded` is what
    that pick actually nets after the bylaws rules below, which can differ
    from `correct * points` (a duplicate-points game, rule 7)."""

    game_id: str
    predicted_winner: str | None
    points: int | None
    actual_winner: str | None
    decided: bool
    correct: bool
    points_awarded: int


@dataclass(frozen=True)
class WeekScore:
    """A week's total score from a set of picks against real outcomes.
    `games_decided < games_total` means the week isn't over yet -- treat
    `total_points` as provisional, not final."""

    total_points: int
    games_decided: int
    games_total: int
    results: list[PickResult]


def score_picks(
    entries: dict[str, tuple[str | None, int | None]], outcomes: pd.DataFrame
) -> WeekScore:
    """Score a set of picks (`game_id -> (predicted_winner, points)` -- the
    same shape `check_actual_picks` takes, so this serves both the
    algorithm's `weekly_picks` and the user's `actual_picks` without a
    second parallel scoring path) against real per-game outcomes
    (`outcomes`: `game_id`/`home_team`/`away_team`/`home_score`/`away_score`,
    as returned by `store.get_game_outcomes`).

    Applies the bylaws rules `check_actual_picks` only flags:

    - Rule 6 (tie): a tied game awards no points to anyone, regardless of
      pick.
    - Rule 16 (blank winner) / Rule 15 (blank points): score as incorrect /
      unawardable, same as any other wrong pick.
    - Rule 7 (duplicate points): when more than one game shares the same
      points value, that value is credited at most once for the whole
      group -- only if at least one game in the group was correct (and
      only once even if more than one was). Confirmed against the actual
      2026 rules document: "If a card has two numbers of the same value,
      the player receives the lower of the two numbers" whether one or
      both choices were correct -- since the two numbers are equal by the
      rule's own premise, "the lower" is trivially that shared value,
      credited once.

    A game with no known outcome yet (`home_score`/`away_score` still
    `NULL`) is excluded from scoring but still counted in `games_total`, so
    `games_decided` can flag a provisional mid-week total instead of
    silently treating an undecided game as wrong.
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
    """Flag a mismatch between the pool's officially reported score and this
    app's own `score_picks` total -- `None` if there's nothing to flag.

    Silent (no flag) when: no reported score has been entered yet; the week
    isn't fully decided (`games_decided < games_total`, so the computed
    total is still provisional); or the card was late (bylaws rule 2's
    penalty -- 10 points below the field's lowest card -- isn't verifiable
    without every other entrant's score, which this app doesn't track, so a
    mismatch there is expected, not a red flag).
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
