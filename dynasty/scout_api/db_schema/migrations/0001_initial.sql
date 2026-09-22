-- Generic mirror of the scout-data git branch's JSON files.
--
-- This sync mechanism's own concern is the generic sync itself, not any
-- particular file's content shape - the real, typed schemas (findings,
-- run records) get defined later, on top of this same file, once they
-- exist. Storing each branch file verbatim by path means a schema
-- introduced later doesn't require a fresh migration here just to become
-- readable locally - a new file on the branch is picked up automatically
-- the next sync.
CREATE TABLE scout_data_files (
    path TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    synced_at TEXT NOT NULL
);
