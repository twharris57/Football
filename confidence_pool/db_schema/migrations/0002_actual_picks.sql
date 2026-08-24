-- Phase 2: track what the user actually submitted to the pool, separate
-- from picks_core's recommendation (weekly_picks). Filled in every week
-- once entered, not just when it deviates from the algorithm -- see
-- docs/confidence-pool-data-model.md.

CREATE TABLE actual_picks (
    season_year INTEGER NOT NULL,
    week INTEGER NOT NULL,
    game_id TEXT NOT NULL REFERENCES games(game_id),
    points INTEGER NOT NULL,
    predicted_winner TEXT NOT NULL REFERENCES teams(abbreviation),
    entered_at TEXT NOT NULL,
    PRIMARY KEY (season_year, week, game_id),
    UNIQUE (season_year, week, points)
);
