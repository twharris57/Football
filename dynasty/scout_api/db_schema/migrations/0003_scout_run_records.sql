-- Real schema for SC-4's run records, landing on top of SC-15's generic
-- path-keyed mirror (scout_data_files) the same way SC-2's scout_findings
-- did - see SC-4 in .claude/PROJECT_PLAN_DYNASTY.md. Populated by
-- sync.ingest_run_records(), which parses each run_*.json row already in
-- scout_data_files via run_record_schema.parse_run_record().
--
-- Split into a run-level table and a per-item table (rather than one row
-- per run with a JSON blob column) specifically so dedup can query
-- scout_run_record_items directly by (player_id, category) across recent
-- runs - the exact access pattern SC-4's own plan entry describes ("scan
-- recent run records for this player+category").
--
-- Keyed on the GitHub path, not on run_date - run_date is the file's own
-- content, not an externally-guaranteed-unique identifier the way path
-- is (matching scout_findings, which keys on path rather than any of a
-- finding's own fields). Keying on run_date instead would let two
-- distinct files that ever happen to claim the same date (a retry, or
-- any off-schedule extra run) silently overwrite each other with no way
-- to detect the collision - ingest_findings() never assumes a finding's
-- own fields are unique either, for the same reason.
--
-- No REFERENCES between these tables or to scout_data_files(path): this
-- connection never enables PRAGMA foreign_keys, so a declared FK here
-- would be silently unenforced (same reasoning as scout_findings).
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

-- id is a derived "path:index" key, not a generated UUID - items have no
-- natural external key of their own (they're inline array entries in one
-- run's file, not separate GitHub files the way findings are), so this
-- is the composite (path, item position) key flattened to one column to
-- fit the same single-column mirroring shape scout_findings already
-- uses. Keyed on path rather than run_date for the same collision
-- reasoning as scout_run_records above.
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
