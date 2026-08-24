"""SQLite persistence for the confidence pool: seasons, teams, the stable
game/schedule facts, weekly odds+picks snapshots, and lock-in status.

Schema lives in `db_schema/migrations/` (applied by `db_schema.apply_migrations`
on every `connect()`) rather than a single inline `CREATE TABLE` script -- see
`docs/confidence-pool-web-app.md` for the full table-by-table design
rationale and `.claude/PROJECT_PLAN_CONFIDENCE_POOL.md`'s `CP-3`/`CP-5` for
why this exists: every week's evaluated games and generated picks are meant
to be real historical input for future what-if analysis, not just a working
cache of "whatever's current."
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pandas as pd

import db_schema

# Seeded once into `teams` on first connect (`INSERT OR IGNORE`, so a later
# Settings-tab edit is never clobbered on a later app restart). Sourced from
# the user directly (2026-08-23) against a real late-season 2025 Legion pool
# sheet, covering all 32 of nfl_data_py's team abbreviations (see
# `picks_core.NFL_TEAM_ABBREVIATIONS`). Still editable via Settings if the
# pool sheet's naming ever changes -- this is just the starting basis, not a
# fixed constant.
DEFAULT_TEAMS: dict[str, str] = {
    "ARI": "Arizona",
    "ATL": "Atlanta",
    "BAL": "Baltimore",
    "BUF": "Buffalo",
    "CAR": "Carolina",
    "CHI": "Chicago",
    "CIN": "Cincinnati",
    "CLE": "Cleveland",
    "DAL": "Dallas",
    "DEN": "Denver",
    "DET": "Detroit",
    "GB": "Green Bay",
    "HOU": "Houston",
    "IND": "Indianapolis",
    "JAX": "Jacksonville",
    "KC": "Kansas City",
    "LA": "LA Rams",
    "LAC": "LA Chargers",
    "LV": "Las Vegas",
    "MIA": "Miami",
    "MIN": "Minnesota",
    "NE": "New England",
    "NO": "New Orleans",
    "NYG": "NY Giants",
    "NYJ": "NY Jets",
    "PHI": "Philadelphia",
    "PIT": "Pittsburgh",
    "SEA": "Seattle",
    "SF": "San Francisco",
    "TB": "Tampa Bay",
    "TEN": "Tennessee",
    "WAS": "Washington",
}


def connect(db_path: str) -> sqlite3.Connection:
    """Open (creating/migrating as needed) the confidence-pool SQLite store."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    db_schema.apply_migrations(conn)
    _seed_default_teams(conn)
    return conn


def _seed_default_teams(conn: sqlite3.Connection) -> None:
    """Insert `DEFAULT_TEAMS` for any team that has no row yet.
    `INSERT OR IGNORE` -- safe to call on every `connect()`, never
    overwrites a name already set (via Settings, or a prior call here)."""
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO teams (abbreviation, display_name) VALUES (?, ?)",
            list(DEFAULT_TEAMS.items()),
        )


def get_team_display_names(conn: sqlite3.Connection) -> dict[str, str]:
    """Return every team's current display name, keyed by abbreviation."""
    rows = conn.execute("SELECT abbreviation, display_name FROM teams").fetchall()
    return {row["abbreviation"]: row["display_name"] for row in rows}


def set_team_display_name(conn: sqlite3.Connection, abbreviation: str, display_name: str) -> None:
    """Set (or update) the pool-sheet display name shown for a team abbreviation."""
    with conn:
        conn.execute(
            """
            INSERT INTO teams (abbreviation, display_name)
            VALUES (?, ?)
            ON CONFLICT(abbreviation) DO UPDATE SET display_name = excluded.display_name
            """,
            (abbreviation, display_name),
        )


def get_season(conn: sqlite3.Connection, season_year: int) -> dict | None:
    """Return the season's config row, or `None` if it has none yet."""
    row = conn.execute(
        "SELECT * FROM seasons WHERE season_year = ?", (season_year,)
    ).fetchone()
    return dict(row) if row else None


def get_active_season(conn: sqlite3.Connection) -> int | None:
    """Return the currently active season year, or `None` if none is set."""
    row = conn.execute("SELECT season_year FROM seasons WHERE active = 1").fetchone()
    return int(row["season_year"]) if row else None


def set_active_season(conn: sqlite3.Connection, season_year: int) -> None:
    """Mark `season_year` active, clearing whichever season was active before.

    `with conn:` -- for `sqlite3.Connection`, this commits the block as one
    transaction on success or rolls it all back on an exception; it does
    *not* close the connection (a common gotcha). Every multi-statement
    write in this module relies on that for atomicity.
    """
    with conn:
        conn.execute("UPDATE seasons SET active = 0")
        conn.execute(
            """
            INSERT INTO seasons (season_year, active)
            VALUES (?, 1)
            ON CONFLICT(season_year) DO UPDATE SET active = 1
            """,
            (season_year,),
        )


def get_week_rule(conn: sqlite3.Connection, season_year: int, week: int) -> dict | None:
    """Return this week's selection/deadline override, or `None` if it
    follows the default `'standard'` rule (see `picks_core.select_games`)."""
    row = conn.execute(
        "SELECT * FROM season_week_rules WHERE season_year = ? AND week = ?",
        (season_year, week),
    ).fetchone()
    return dict(row) if row else None


def set_late_season_deadline(
    conn: sqlite3.Connection, season_year: int, week: int, deadline: datetime
) -> None:
    """Set the commissioner-announced early cutoff for week 17 or 18,
    marking that week's selection rule as `'all_games'` (see `CP-19`/`CP-21`
    -- every game counts for these weeks; only the deadline is special)."""
    if week not in (17, 18):
        raise ValueError(f"Late-season deadline only applies to weeks 17/18, got {week}")
    with conn:
        conn.execute("INSERT OR IGNORE INTO seasons (season_year) VALUES (?)", (season_year,))
        conn.execute(
            """
            INSERT INTO season_week_rules (season_year, week, selection_rule, deadline_override)
            VALUES (?, ?, 'all_games', ?)
            ON CONFLICT(season_year, week) DO UPDATE SET
                selection_rule = 'all_games',
                deadline_override = excluded.deadline_override
            """,
            (season_year, week, deadline.isoformat()),
        )


def register_algorithm_version(conn: sqlite3.Connection, version_id: str, description: str) -> None:
    """Ensure `version_id` is recorded in `algorithm_versions` -- idempotent,
    never overwrites an existing row's description once introduced. Called
    once at app startup (see `streamlit_app.py`) with `picks_core.ALGORITHM_VERSION`,
    so every `weekly_picks` row's `algorithm_version` FK is always satisfiable."""
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO algorithm_versions (version_id, description, introduced_at) VALUES (?, ?, ?)",
            (version_id, description, datetime.now(timezone.utc).isoformat()),
        )


def sync_game_outcomes(conn: sqlite3.Connection, schedule: pd.DataFrame, synced_at: datetime) -> None:
    """Backfill final scores onto already-known `games` rows from a fresh
    schedule fetch (`nfl_data_py`'s `home_score`/`away_score` columns, `NULL`
    until a game completes). Update-only -- never inserts a new `games` row,
    so a game the pool never selected (and so never reached `save_week()`)
    stays out of this table entirely, matching `select_games()`'s own scope.
    """
    has_scores = schedule["home_score"].notna() & schedule["away_score"].notna()
    rows = schedule[has_scores]
    with conn:
        conn.executemany(
            "UPDATE games SET home_score = ?, away_score = ?, outcome_synced_at = ? WHERE game_id = ?",
            [
                (row["home_score"], row["away_score"], synced_at.isoformat(), row["game_id"])
                for _, row in rows.iterrows()
            ],
        )


def get_week_status(conn: sqlite3.Connection, season_year: int, week: int) -> dict | None:
    """Return a week's lock/generation status, or `None` if nothing's been
    saved for it yet."""
    row = conn.execute(
        "SELECT * FROM week_status WHERE season_year = ? AND week = ?",
        (season_year, week),
    ).fetchone()
    return dict(row) if row else None


def save_week(
    conn: sqlite3.Connection,
    season_year: int,
    week: int,
    games: pd.DataFrame,
    picks: pd.DataFrame,
    generated_at: datetime,
    first_snapshot_eligible: bool,
    lock: bool = False,
) -> None:
    """Persist a week's evaluated games + generated picks as the `'current'`
    snapshot, overwriting any prior `'current'` snapshot for that week.
    Refuses to overwrite an already-locked week.

    On the first save for a `(season_year, week)` that's also
    `first_snapshot_eligible`, also captures an immutable `'first'`
    snapshot -- written once, never touched again -- so odds/pick movement
    between the first real review and the eventual lock stays visible
    later (see `docs/confidence-pool-web-app.md`). Deliberately *not* just
    "the first save ever": a save made while previewing a future week (the
    season/week selector lets you browse ahead) shouldn't get permanently
    recorded as that week's first look -- pass `picks_core.is_first_look_window(...)`
    so only a save made close to the week's actual kickoffs can claim it.

    `games` needs `game_id`/`home_team`/`away_team`/`gameday`/`weekday`/
    `gametime`/`home_moneyline`/`away_moneyline`/`included` columns (as
    produced by `picks_core.games_with_included_flags`); `picks` needs
    `game_id`/`points`/`predicted_winner`/`confidence`/`algorithm_version`
    (as produced by `picks_core.rank_games`).
    """
    status = get_week_status(conn, season_year, week)
    if status and status["locked"]:
        raise ValueError(f"Week {week} ({season_year}) is locked -- cannot regenerate")

    has_first_snapshot = conn.execute(
        """
        SELECT 1 FROM weekly_games wg
        JOIN games g ON wg.game_id = g.game_id
        WHERE g.season_year = ? AND g.week = ? AND wg.snapshot_type = 'first'
        LIMIT 1
        """,
        (season_year, week),
    ).fetchone() is not None
    snapshot_types = ["current"]
    if not has_first_snapshot and first_snapshot_eligible:
        snapshot_types.append("first")

    with conn:
        conn.executemany(
            """
            INSERT INTO games (game_id, season_year, week, home_team, away_team, gameday, weekday, gametime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_id) DO UPDATE SET
                home_team = excluded.home_team,
                away_team = excluded.away_team,
                gameday = excluded.gameday,
                weekday = excluded.weekday,
                gametime = excluded.gametime
            """,
            [
                (
                    row["game_id"], season_year, week,
                    row["home_team"], row["away_team"],
                    str(row["gameday"]), row["weekday"], row["gametime"],
                )
                for _, row in games.iterrows()
            ],
        )

        conn.execute(
            """
            DELETE FROM weekly_games WHERE snapshot_type = 'current' AND game_id IN
                (SELECT game_id FROM games WHERE season_year = ? AND week = ?)
            """,
            (season_year, week),
        )
        conn.execute(
            """
            DELETE FROM weekly_picks WHERE snapshot_type = 'current' AND game_id IN
                (SELECT game_id FROM games WHERE season_year = ? AND week = ?)
            """,
            (season_year, week),
        )

        for snapshot_type in snapshot_types:
            conn.executemany(
                """
                INSERT INTO weekly_games (game_id, snapshot_type, home_moneyline, away_moneyline, included, captured_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["game_id"], snapshot_type,
                        row["home_moneyline"], row["away_moneyline"],
                        int(row.get("included", True)), generated_at.isoformat(),
                    )
                    for _, row in games.iterrows()
                ],
            )
            conn.executemany(
                """
                INSERT INTO weekly_picks (game_id, snapshot_type, points, predicted_winner, confidence, algorithm_version)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["game_id"], snapshot_type,
                        int(row["points"]), row["predicted_winner"], row["confidence"],
                        row["algorithm_version"],
                    )
                    for _, row in picks.iterrows()
                ],
            )

        conn.execute(
            """
            INSERT INTO week_status (season_year, week, locked, locked_at, generated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(season_year, week) DO UPDATE SET
                locked = excluded.locked,
                locked_at = excluded.locked_at,
                generated_at = excluded.generated_at
            """,
            (
                season_year, week, int(lock),
                generated_at.isoformat() if lock else None,
                generated_at.isoformat(),
            ),
        )


def load_week(
    conn: sqlite3.Connection, season_year: int, week: int
) -> tuple[pd.DataFrame, pd.DataFrame, dict | None]:
    """Load a previously-saved week's `'current'` games, picks, and status.
    Empty DataFrames (and `None` status) if nothing has been saved for it yet.
    """
    games = pd.read_sql_query(
        """
        SELECT g.game_id, g.home_team, g.away_team, g.gameday, g.weekday, g.gametime,
               wg.home_moneyline, wg.away_moneyline, wg.included
        FROM weekly_games wg
        JOIN games g ON wg.game_id = g.game_id
        WHERE g.season_year = ? AND g.week = ? AND wg.snapshot_type = 'current'
        ORDER BY g.gameday, g.gametime
        """,
        conn,
        params=(season_year, week),
    )
    picks = pd.read_sql_query(
        """
        SELECT wp.game_id, wp.points, wp.predicted_winner, wp.confidence, wp.algorithm_version
        FROM weekly_picks wp
        JOIN games g ON wp.game_id = g.game_id
        WHERE g.season_year = ? AND g.week = ? AND wp.snapshot_type = 'current'
        ORDER BY wp.points DESC
        """,
        conn,
        params=(season_year, week),
    )
    status = get_week_status(conn, season_year, week)
    return games, picks, status
