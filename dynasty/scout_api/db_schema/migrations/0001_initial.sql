-- Verbatim mirror of the scout-data branch's files, keyed by path.

CREATE TABLE scout_data_files (
    path TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    synced_at TEXT NOT NULL
);
