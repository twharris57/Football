-- Phase 2: track what the user actually submitted to the pool, separate
-- from picks_core's recommendation (weekly_picks). Filled in every week
-- once entered, not just when it deviates from the algorithm -- see
-- docs/confidence-pool-data-model.md.
--
-- points/predicted_winner are nullable and duplicate points across games
-- are allowed on purpose -- the real 2026 Legion Pool bylaws define exact
-- resolutions for a blank point box (rule 15), an unmarked winner (rule
-- 16), and two games sharing the same points value (rule 7), none of
-- which invalidate the submission. This table records what was actually
-- written, irregularities included, not a "corrected" version of it --
-- see picks_core.check_actual_picks().

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
-- row of one generation event. Bylaws rule 2: a late card is not
-- excluded, it's docked 10 points below that week's lowest card -- needs
-- the field's scores (weekly_standings, Phase 3) to actually compute,
-- so this only records the fact for now; see picks_core.check_actual_picks().
