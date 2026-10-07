-- IF NOT EXISTS: databases created before migrations already have this table.

CREATE TABLE IF NOT EXISTS trade_block (
    sleeper_id TEXT PRIMARY KEY,
    roster_id INTEGER NOT NULL,
    added_date TEXT NOT NULL
);
