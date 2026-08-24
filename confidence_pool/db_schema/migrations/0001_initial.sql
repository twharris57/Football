-- Origin schema for the confidence-pool app's SQLite store.
--
-- This is a fresh design (see docs/confidence-pool-web-app.md), not a
-- replay of the app's pre-migration development history -- the app never
-- held real production data before this migration, so there is nothing
-- to preserve by re-deriving that history as separate steps.

CREATE TABLE seasons (
    season_year INTEGER PRIMARY KEY,
    active INTEGER NOT NULL DEFAULT 0,
    sunday_afternoon_cutoff TEXT NOT NULL DEFAULT '13:00'
);

-- Only weeks whose game-selection/deadline rule differs from the default
-- ("standard": Sunday-afternoon + Monday, deadline = earliest kickoff) get
-- a row here -- see picks_core.select_games()/week_deadline().
CREATE TABLE season_week_rules (
    season_year INTEGER NOT NULL REFERENCES seasons(season_year),
    week INTEGER NOT NULL,
    selection_rule TEXT NOT NULL CHECK (selection_rule IN ('standard', 'all_games')),
    deadline_override TEXT,
    PRIMARY KEY (season_year, week)
);

CREATE TABLE teams (
    abbreviation TEXT PRIMARY KEY,
    display_name TEXT NOT NULL
);

-- The stable schedule + outcome fact for a game -- teams, kickoff, and
-- (once known) the final score. Synced from nfl_data_py's schedule export,
-- not re-derived from a weekly snapshot.
CREATE TABLE games (
    game_id TEXT PRIMARY KEY,
    season_year INTEGER NOT NULL,
    week INTEGER NOT NULL,
    home_team TEXT NOT NULL REFERENCES teams(abbreviation),
    away_team TEXT NOT NULL REFERENCES teams(abbreviation),
    gameday TEXT NOT NULL,
    weekday TEXT NOT NULL,
    gametime TEXT NOT NULL,
    home_score REAL,
    away_score REAL,
    outcome_synced_at TEXT
);

CREATE TABLE algorithm_versions (
    version_id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    introduced_at TEXT NOT NULL
);

-- A game's evaluated odds/inclusion at a point in time. 'current' is the
-- live working snapshot (overwritten on every regenerate, frozen once
-- week_status.locked = 1); 'first' is captured once, on the very first
-- save ever made for a (season_year, week), and never touched again.
CREATE TABLE weekly_games (
    game_id TEXT NOT NULL REFERENCES games(game_id),
    snapshot_type TEXT NOT NULL CHECK (snapshot_type IN ('current', 'first')),
    home_moneyline REAL,
    away_moneyline REAL,
    included INTEGER NOT NULL DEFAULT 1,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (game_id, snapshot_type)
);

CREATE TABLE weekly_picks (
    game_id TEXT NOT NULL REFERENCES games(game_id),
    snapshot_type TEXT NOT NULL CHECK (snapshot_type IN ('current', 'first')),
    points INTEGER NOT NULL,
    predicted_winner TEXT NOT NULL REFERENCES teams(abbreviation),
    confidence REAL NOT NULL,
    algorithm_version TEXT NOT NULL REFERENCES algorithm_versions(version_id),
    PRIMARY KEY (game_id, snapshot_type)
);

CREATE TABLE week_status (
    season_year INTEGER NOT NULL,
    week INTEGER NOT NULL,
    locked INTEGER NOT NULL DEFAULT 0,
    locked_at TEXT,
    generated_at TEXT NOT NULL,
    PRIMARY KEY (season_year, week)
);
