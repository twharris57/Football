"""Tests for dynasty/trade_block_migrations -- schema and one-time seed, against real SQLite files."""

from __future__ import annotations

import sqlite3

import trade_block_store
from dynasty_core.trade_block import TradeBlockEntry

SEED_COUNT = 22
SEEDED_PURDY = TradeBlockEntry(sleeper_id="8183", roster_id=1, added_date="2026-10-06")


def _sleeper_ids(conn: sqlite3.Connection) -> set[str]:
    return {entry.sleeper_id for entry in trade_block_store.get_trade_block(conn)}


class TestFreshDatabase:
    def test_fresh_database_contains_the_seed(self, tmp_path):
        conn = trade_block_store.connect(str(tmp_path / "trade_block.db"))

        entries = trade_block_store.get_trade_block(conn)

        assert len(entries) == SEED_COUNT
        assert SEEDED_PURDY in entries

    def test_every_migration_is_recorded(self, tmp_path):
        conn = trade_block_store.connect(str(tmp_path / "trade_block.db"))

        versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]

        assert versions == [1, 2]


class TestSeedRunsOnce:
    def test_removed_seed_entry_stays_removed_after_reconnect(self, tmp_path):
        path = str(tmp_path / "trade_block.db")
        conn = trade_block_store.connect(path)
        trade_block_store.remove_trade_block_entry(conn, SEEDED_PURDY.sleeper_id)
        conn.close()

        reopened = trade_block_store.connect(path)

        assert SEEDED_PURDY.sleeper_id not in _sleeper_ids(reopened)
        assert len(trade_block_store.get_trade_block(reopened)) == SEED_COUNT - 1


class TestPreMigrationDatabase:
    def _legacy_db(self, tmp_path, rows: list[tuple[str, int, str]]) -> str:
        """A database from before migrations: the table exists, `schema_migrations` doesn't."""
        path = str(tmp_path / "trade_block.db")
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE trade_block (sleeper_id TEXT PRIMARY KEY, roster_id INTEGER NOT NULL, added_date TEXT NOT NULL)"
        )
        conn.executemany("INSERT INTO trade_block VALUES (?, ?, ?)", rows)
        conn.commit()
        conn.close()
        return path

    def test_existing_entries_are_kept_and_the_seed_is_added(self, tmp_path):
        path = self._legacy_db(tmp_path, [("11563", 3, "2026-10-05")])

        conn = trade_block_store.connect(path)

        assert "11563" in _sleeper_ids(conn)
        assert len(trade_block_store.get_trade_block(conn)) == SEED_COUNT + 1

    def test_already_listed_seed_player_keeps_its_original_entry(self, tmp_path):
        path = self._legacy_db(tmp_path, [("8183", 4, "2026-09-01")])

        conn = trade_block_store.connect(path)

        entries = trade_block_store.get_trade_block(conn)
        assert TradeBlockEntry(sleeper_id="8183", roster_id=4, added_date="2026-09-01") in entries
        assert SEEDED_PURDY not in entries
