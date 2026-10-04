"""SQLite persistence for the confidence pool. Schema: `db_schema/migrations/`."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pandas as pd

import db_schema

# Pool-sheet names, seeded on connect without overwriting Settings edits.
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
    """Open the store, applying migrations and seeding teams.

    Shared across Streamlit threads via `st.cache_resource`, hence
    `check_same_thread=False`. WAL + `busy_timeout` make concurrent writers wait
    instead of failing with "database is locked".
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA journal_mode = WAL")
    db_schema.apply_migrations(conn)
    _seed_default_teams(conn)
    return conn


def _seed_default_teams(conn: sqlite3.Connection) -> None:
    """Insert `DEFAULT_TEAMS` for any team without a row."""
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
    """Set the pool-sheet display name for a team."""
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


def known_seasons(conn: sqlite3.Connection) -> list[int]:
    """Every season year with a `seasons` or `games` row."""
    rows = conn.execute(
        "SELECT season_year FROM seasons UNION SELECT season_year FROM games ORDER BY season_year"
    ).fetchall()
    return [int(row["season_year"]) for row in rows]


def set_active_season(conn: sqlite3.Connection, season_year: int) -> None:
    """Mark `season_year` active, deactivating any other."""
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


# Default 'all_games' weeks before a season_week_rules row exists. Set by the
# bylaws and changes yearly (17-18 in 2025, 16-18 in 2026) — re-check each season.
KNOWN_LATE_SEASON_WEEKS = (16, 17, 18)


def get_week_rule(conn: sqlite3.Connection, season_year: int, week: int) -> dict | None:
    """This week's rule override, or `None` for `'standard'`.

    `KNOWN_LATE_SEASON_WEEKS` default to `'all_games'` even with no row, so they select
    correctly before anyone configures a deadline.
    """
    row = conn.execute(
        "SELECT * FROM season_week_rules WHERE season_year = ? AND week = ?",
        (season_year, week),
    ).fetchone()
    if row:
        return dict(row)
    if week in KNOWN_LATE_SEASON_WEEKS:
        return {
            "season_year": season_year,
            "week": week,
            "selection_rule": "all_games",
            "deadline_override": None,
        }
    return None


def set_late_season_deadline(
    conn: sqlite3.Connection, season_year: int, week: int, deadline: datetime
) -> None:
    """Set a week's commissioner-announced deadline and mark it `'all_games'`. Any week 1-18."""
    if not 1 <= week <= 18:
        raise ValueError(f"Week must be between 1 and 18, got {week}")
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
    """Record `version_id` if new; existing descriptions are never overwritten."""
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO algorithm_versions (version_id, description, introduced_at) VALUES (?, ?, ?)",
            (version_id, description, datetime.now(timezone.utc).isoformat()),
        )


def sync_game_outcomes(conn: sqlite3.Connection, schedule: pd.DataFrame, synced_at: datetime) -> None:
    """Backfill final scores onto existing `games` rows. Never inserts."""
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


def get_game_outcomes(conn: sqlite3.Connection, season_year: int, week: int) -> pd.DataFrame:
    """Teams and scores (null until final) for a week's known games."""
    return pd.read_sql_query(
        """
        SELECT game_id, home_team, away_team, home_score, away_score
        FROM games
        WHERE season_year = ? AND week = ?
        """,
        conn,
        params=(season_year, week),
    )


def set_reported_score(
    conn: sqlite3.Connection,
    season_year: int,
    week: int,
    score: int | None,
    entered_at: datetime,
) -> None:
    """Record the pool's official score for an already-locked week."""
    with conn:
        conn.execute(
            """
            UPDATE week_status
            SET reported_score = ?, reported_score_entered_at = ?
            WHERE season_year = ? AND week = ?
            """,
            (
                score,
                entered_at.isoformat() if score is not None else None,
                season_year,
                week,
            ),
        )


def get_week_status(conn: sqlite3.Connection, season_year: int, week: int) -> dict | None:
    """Return a week's lock/generation status, or `None` if nothing's saved."""
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
    lock_warning: str | None = None,
) -> None:
    """Replace the week's `'current'` snapshot. Raises if the week is locked.

    Also writes the one-time `'first'` snapshot when none exists and
    `first_snapshot_eligible`. `games` comes from `games_with_included_flags`,
    `picks` from `rank_games`. `lock_warning` is stored only when locking.
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
            INSERT INTO week_status (season_year, week, locked, locked_at, generated_at, lock_warning)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(season_year, week) DO UPDATE SET
                locked = excluded.locked,
                locked_at = excluded.locked_at,
                generated_at = excluded.generated_at,
                lock_warning = excluded.lock_warning
            """,
            (
                season_year, week, int(lock),
                generated_at.isoformat() if lock else None,
                generated_at.isoformat(),
                lock_warning if lock else None,
            ),
        )


def load_week(
    conn: sqlite3.Connection, season_year: int, week: int, snapshot_type: str = "current"
) -> tuple[pd.DataFrame, pd.DataFrame, dict | None]:
    """Load one snapshot's games and picks, plus the week's status.

    `games` includes `captured_at` so a reused snapshot keeps its original timestamp.
    """
    games = pd.read_sql_query(
        """
        SELECT g.game_id, g.home_team, g.away_team, g.gameday, g.weekday, g.gametime,
               wg.home_moneyline, wg.away_moneyline, wg.included, wg.captured_at
        FROM weekly_games wg
        JOIN games g ON wg.game_id = g.game_id
        WHERE g.season_year = ? AND g.week = ? AND wg.snapshot_type = ?
        ORDER BY g.gameday, g.gametime
        """,
        conn,
        params=(season_year, week, snapshot_type),
    )
    picks = pd.read_sql_query(
        """
        SELECT wp.game_id, wp.points, wp.predicted_winner, wp.confidence, wp.algorithm_version
        FROM weekly_picks wp
        JOIN games g ON wp.game_id = g.game_id
        WHERE g.season_year = ? AND g.week = ? AND wp.snapshot_type = ?
        ORDER BY wp.points DESC
        """,
        conn,
        params=(season_year, week, snapshot_type),
    )
    status = get_week_status(conn, season_year, week)
    return games, picks, status


def save_actual_picks(
    conn: sqlite3.Connection,
    season_year: int,
    week: int,
    picks: pd.DataFrame,
    entered_at: datetime,
    late: bool = False,
) -> None:
    """Replace the week's submitted card.

    Blank points/winners and duplicate points are stored as entered (the bylaws
    resolve them). `late` applies to the whole card.
    """
    with conn:
        conn.execute(
            "DELETE FROM actual_picks WHERE season_year = ? AND week = ?",
            (season_year, week),
        )
        conn.executemany(
            """
            INSERT INTO actual_picks (season_year, week, game_id, points, predicted_winner, late, entered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    season_year, week, row["game_id"],
                    int(row["points"]) if pd.notna(row["points"]) else None,
                    row["predicted_winner"] if pd.notna(row["predicted_winner"]) else None,
                    int(late), entered_at.isoformat(),
                )
                for _, row in picks.iterrows()
            ],
        )


def load_actual_picks(conn: sqlite3.Connection, season_year: int, week: int) -> pd.DataFrame:
    """Load the week's submitted card (empty if none)."""
    return pd.read_sql_query(
        """
        SELECT game_id, points, predicted_winner, late, entered_at
        FROM actual_picks
        WHERE season_year = ? AND week = ?
        ORDER BY points DESC
        """,
        conn,
        params=(season_year, week),
    )
