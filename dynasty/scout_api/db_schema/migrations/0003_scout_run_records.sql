-- Typed run records. Items get their own table so dedup can query (player_id, category).
-- Keyed by GitHub path, not run_date, so a same-day retry can't overwrite. No FKs.

CREATE TABLE scout_run_records (
    path TEXT PRIMARY KEY,
    run_date TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    notification_fired INTEGER NOT NULL,
    reflection_reviewed_at TEXT,
    reflection_notes TEXT,
    reflection_issue_url TEXT
);
CREATE INDEX idx_scout_run_records_run_date ON scout_run_records (run_date);

-- id is "path:index"; items have no external key of their own.
CREATE TABLE scout_run_record_items (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    run_date TEXT NOT NULL,
    player_id TEXT NOT NULL,
    category TEXT NOT NULL,
    verdict_lane TEXT NOT NULL,
    verdict TEXT NOT NULL,
    reason TEXT NOT NULL,
    source_path TEXT
);
CREATE INDEX idx_scout_run_record_items_dedup ON scout_run_record_items (player_id, category);
CREATE INDEX idx_scout_run_record_items_run_date ON scout_run_record_items (run_date);
