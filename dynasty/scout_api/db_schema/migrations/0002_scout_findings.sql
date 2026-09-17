-- Real schema for the templated finding records (see finding_schema.py
-- for the full design), landing on top of the generic path-keyed mirror
-- (scout_data_files) now that the shape is defined. Populated by
-- sync.ingest_findings(), which parses each finding_*.json row already
-- in scout_data_files via finding_schema.parse_finding().
--
-- No REFERENCES to scout_data_files(path): this connection never enables
-- PRAGMA foreign_keys, so a declared FK here would be silently
-- unenforced. ingest_findings() does its own explicit stale-row cleanup
-- instead, mirroring sync()'s own pattern for scout_data_files itself.
CREATE TABLE scout_findings (
    path TEXT PRIMARY KEY,
    player_id TEXT NOT NULL,
    category TEXT NOT NULL,
    summary TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_scout_findings_player_id ON scout_findings (player_id);
