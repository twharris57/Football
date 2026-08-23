"""SQLite persistence for weekly confidence-pool picks and season config.

Every week's evaluated game list and generated recommendation get saved
here so future analysis (what-if scoring, an eventual analytics API -- see
`.claude/PROJECT_PLAN_CONFIDENCE_POOL.md`'s `CP-3`/`CP-5`) has real
historical input instead of needing to reconstruct it later. See
`docs/confidence-pool-web-app.md` for the schema's design rationale.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS season_config (
    season_year INTEGER PRIMARY KEY,
    active INTEGER NOT NULL DEFAULT 0,
    week17_deadline TEXT,
    week18_deadline TEXT
);

CREATE TABLE IF NOT EXISTS week_status (
    season_year INTEGER NOT NULL,
    week INTEGER NOT NULL,
    locked INTEGER NOT NULL DEFAULT 0,
    locked_at TEXT,
    generated_at TEXT NOT NULL,
    PRIMARY KEY (season_year, week)
);

CREATE TABLE IF NOT EXISTS weekly_games (
    season_year INTEGER NOT NULL,
    week INTEGER NOT NULL,
    game_id TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_moneyline REAL,
    away_moneyline REAL,
    gameday TEXT NOT NULL,
    weekday TEXT NOT NULL,
    gametime TEXT NOT NULL,
    included INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (season_year, week, game_id)
);

CREATE TABLE IF NOT EXISTS weekly_picks (
    season_year INTEGER NOT NULL,
    week INTEGER NOT NULL,
    game_id TEXT NOT NULL,
    points INTEGER NOT NULL,
    predicted_winner TEXT NOT NULL,
    confidence REAL NOT NULL,
    PRIMARY KEY (season_year, week, game_id)
);

CREATE TABLE IF NOT EXISTS team_display_names (
    abbreviation TEXT PRIMARY KEY,
    display_name TEXT NOT NULL
);
"""

# Seeded once into `team_display_names` on first connect (`INSERT OR IGNORE`, so a
# later Settings-tab edit is never clobbered on a later app restart). Sourced from
# the user directly (2026-08-23) against a real late-season 2025 Legion pool sheet,
# covering all 32 of nfl_data_py's team abbreviations (see
# `picks_core.NFL_TEAM_ABBREVIATIONS`). Still editable via Settings if the pool
# sheet's naming ever changes -- this is just the starting basis, not a fixed
# constant.
DEFAULT_TEAM_DISPLAY_NAMES: dict[str, str] = {
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
    """Open (creating if needed) the confidence-pool SQLite store."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _seed_default_team_display_names(conn)
    return conn


def _seed_default_team_display_names(conn: sqlite3.Connection) -> None:
    """Insert `DEFAULT_TEAM_DISPLAY_NAMES` for any team that has no override
    yet. `INSERT OR IGNORE` -- safe to call on every `connect()`, never
    overwrites a name already set (via Settings, or a prior call here)."""
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO team_display_names (abbreviation, display_name) VALUES (?, ?)",
            list(DEFAULT_TEAM_DISPLAY_NAMES.items()),
        )


def get_season_config(conn: sqlite3.Connection, season_year: int) -> dict | None:
    """Return the season's config row, or `None` if it has none yet."""
    row = conn.execute(
        "SELECT * FROM season_config WHERE season_year = ?", (season_year,)
    ).fetchone()
    return dict(row) if row else None


def get_active_season(conn: sqlite3.Connection) -> int | None:
    """Return the currently active season year, or `None` if none is set."""
    row = conn.execute(
        "SELECT season_year FROM season_config WHERE active = 1"
    ).fetchone()
    return int(row["season_year"]) if row else None


def set_active_season(conn: sqlite3.Connection, season_year: int) -> None:
    """Mark `season_year` active, clearing whichever season was active before.

    `with conn:` -- for `sqlite3.Connection`, this commits the block as one
    transaction on success or rolls it all back on an exception; it does
    *not* close the connection (a common gotcha). Every multi-statement
    write in this module relies on that for atomicity.
    """
    with conn:
        conn.execute("UPDATE season_config SET active = 0")
        conn.execute(
            """
            INSERT INTO season_config (season_year, active)
            VALUES (?, 1)
            ON CONFLICT(season_year) DO UPDATE SET active = 1
            """,
            (season_year,),
        )


def set_late_season_deadline(
    conn: sqlite3.Connection, season_year: int, week: int, deadline: datetime
) -> None:
    """Set the commissioner-announced early cutoff for week 17 or 18."""
    if week not in (17, 18):
        raise ValueError(f"Late-season deadline only applies to weeks 17/18, got {week}")
    column = f"week{week}_deadline"
    with conn:
        conn.execute(
            f"""
            INSERT INTO season_config (season_year, {column})
            VALUES (?, ?)
            ON CONFLICT(season_year) DO UPDATE SET {column} = excluded.{column}
            """,
            (season_year, deadline.isoformat()),
        )


def get_week_status(conn: sqlite3.Connection, season_year: int, week: int) -> dict | None:
    """Return a week's lock/generation status, or `None` if nothing's been
    saved for it yet."""
    row = conn.execute(
        "SELECT * FROM week_status WHERE season_year = ? AND week = ?",
        (season_year, week),
    ).fetchone()
    return dict(row) if row else None


def get_team_display_names(conn: sqlite3.Connection) -> dict[str, str]:
    """Return every configured team-abbreviation -> pool-sheet display-name
    override. A team with no entry here has no override yet -- callers
    should fall back to showing its raw abbreviation."""
    rows = conn.execute("SELECT abbreviation, display_name FROM team_display_names").fetchall()
    return {row["abbreviation"]: row["display_name"] for row in rows}


def set_team_display_name(conn: sqlite3.Connection, abbreviation: str, display_name: str) -> None:
    """Set (or update) the pool-sheet display name shown for a team abbreviation."""
    with conn:
        conn.execute(
            """
            INSERT INTO team_display_names (abbreviation, display_name)
            VALUES (?, ?)
            ON CONFLICT(abbreviation) DO UPDATE SET display_name = excluded.display_name
            """,
            (abbreviation, display_name),
        )


def save_week(
    conn: sqlite3.Connection,
    season_year: int,
    week: int,
    games: pd.DataFrame,
    picks: pd.DataFrame,
    generated_at: datetime,
    lock: bool = False,
) -> None:
    """Persist a week's evaluated games + generated picks, overwriting any
    prior snapshot for that week. Refuses to overwrite an already-locked week.
    """
    status = get_week_status(conn, season_year, week)
    if status and status["locked"]:
        raise ValueError(
            f"Week {week} ({season_year}) is locked -- cannot regenerate"
        )

    with conn:
        conn.execute(
            "DELETE FROM weekly_games WHERE season_year = ? AND week = ?",
            (season_year, week),
        )
        conn.execute(
            "DELETE FROM weekly_picks WHERE season_year = ? AND week = ?",
            (season_year, week),
        )
        conn.executemany(
            """
            INSERT INTO weekly_games (
                season_year, week, game_id, home_team, away_team,
                home_moneyline, away_moneyline, gameday, weekday, gametime, included
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    season_year,
                    week,
                    row["game_id"],
                    row["home_team"],
                    row["away_team"],
                    row["home_moneyline"],
                    row["away_moneyline"],
                    str(row["gameday"]),
                    row["weekday"],
                    row["gametime"],
                    int(row.get("included", True)),
                )
                for _, row in games.iterrows()
            ],
        )
        conn.executemany(
            """
            INSERT INTO weekly_picks (
                season_year, week, game_id, points, predicted_winner, confidence
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    season_year,
                    week,
                    row["game_id"],
                    int(row["points"]),
                    row["predicted_winner"],
                    row["confidence"],
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
                season_year,
                week,
                int(lock),
                generated_at.isoformat() if lock else None,
                generated_at.isoformat(),
            ),
        )


def load_week(
    conn: sqlite3.Connection, season_year: int, week: int
) -> tuple[pd.DataFrame, pd.DataFrame, dict | None]:
    """Load a previously-saved week's games, picks, and status. Empty
    DataFrames (and `None` status) if nothing has been saved for it yet.
    """
    games = pd.read_sql_query(
        "SELECT * FROM weekly_games WHERE season_year = ? AND week = ? ORDER BY gameday, gametime",
        conn,
        params=(season_year, week),
    )
    picks = pd.read_sql_query(
        "SELECT * FROM weekly_picks WHERE season_year = ? AND week = ? ORDER BY points DESC",
        conn,
        params=(season_year, week),
    )
    status = get_week_status(conn, season_year, week)
    return games, picks, status
