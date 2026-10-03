-- The card actually submitted. Nullable fields and duplicate points are
-- deliberate: record what was written; the bylaws resolve it. `late` is per week.

CREATE TABLE actual_picks (
    season_year INTEGER NOT NULL,
    week INTEGER NOT NULL,
    game_id TEXT NOT NULL REFERENCES games(game_id),
    points INTEGER,
    predicted_winner TEXT REFERENCES teams(abbreviation),
    late INTEGER NOT NULL DEFAULT 0,
    entered_at TEXT NOT NULL,
    PRIMARY KEY (season_year, week, game_id)
);
