-- Phase 2: track what the user actually submitted to the pool, separate
-- from picks_core's recommendation (weekly_picks). Filled in every week
-- once entered, not just when it deviates from the algorithm -- see
-- docs/confidence-pool-data-model.md.
--
-- points/predicted_winner are nullable and duplicate points across games
-- are allowed on purpose -- this table records what was actually written,
-- irregularities included, not a "corrected" version of it. The bylaws'
-- own resolution for each irregularity (which never invalidates the
-- submission) is documented once, in full, at picks_core.check_actual_picks().

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
-- `late` is a per-week fact (the whole card was submitted late, not one
-- game) stored redundantly on every row for that week -- same pattern as
-- `weekly_games.captured_at`, which is likewise identical across every
-- row of one generation event. Its bylaws penalty needs real per-game
-- scores to compute (weekly_standings, a future phase) -- this only
-- records the fact for now.
