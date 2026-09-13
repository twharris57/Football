-- Generic mirror of the scout-data git branch's JSON files.
--
-- SC-15's own concern is the sync mechanism itself, not the finding/dedup
-- schema (SC-2/SC-4 define those content shapes later, on top of this
-- same file, once they exist). Storing each branch file verbatim by path
-- means the real schema those items introduce doesn't require a fresh
-- migration here just to become readable locally - a new file on the
-- branch is picked up automatically the next sync.
CREATE TABLE scout_data_files (
    path TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    synced_at TEXT NOT NULL
);
