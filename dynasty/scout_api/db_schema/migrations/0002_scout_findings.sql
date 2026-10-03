-- Typed findings parsed from finding_*.json. No FKs: foreign_keys is never enabled here.

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
