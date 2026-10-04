-- Origin schema.

CREATE TABLE seasons (
    season_year INTEGER PRIMARY KEY,
    active INTEGER NOT NULL DEFAULT 0,
    sunday_afternoon_cutoff TEXT NOT NULL DEFAULT '13:00'
);

-- Rows only for weeks whose rule differs from 'standard'.
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

-- 'current' is overwritten until lock; 'first' is written once, in the first-look window.
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
