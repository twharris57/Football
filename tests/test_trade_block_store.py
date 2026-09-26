"""Tests for dynasty.trade_block_store -- SQLite persistence, in-memory
only (no real file on disk), per testing.md.

Named test_trade_block_store.py, not test_store.py, since dynasty and
confidence_pool both land on the same sys.path (conftest.py) and a
same-named test module here would collide with
tests/confidence_pool/test_store.py's module name.
"""

from __future__ import annotations

import sqlite3

import pytest

import trade_block_store
from dynasty_core.trade_block import TradeBlockEntry


@pytest.fixture
def conn():
    return trade_block_store.connect(":memory:")


class TestGetTradeBlock:
    def test_empty_store_returns_empty_tuple(self, conn):
        assert trade_block_store.get_trade_block(conn) == ()

    def test_added_entries_round_trip(self, conn):
        trade_block_store.add_trade_block_entry(conn, "7523", 1, "2026-09-22")
        trade_block_store.add_trade_block_entry(conn, "5927", 2, "2026-09-20")

        entries = trade_block_store.get_trade_block(conn)

        assert set(entries) == {
            TradeBlockEntry(sleeper_id="7523", roster_id=1, added_date="2026-09-22"),
            TradeBlockEntry(sleeper_id="5927", roster_id=2, added_date="2026-09-20"),
        }


class TestAddTradeBlockEntry:
    def test_duplicate_sleeper_id_raises(self, conn):
        trade_block_store.add_trade_block_entry(conn, "7523", 1, "2026-09-22")

        with pytest.raises(sqlite3.IntegrityError):
            trade_block_store.add_trade_block_entry(conn, "7523", 6, "2026-09-23")


class TestRemoveTradeBlockEntry:
    def test_removes_the_matching_entry(self, conn):
        trade_block_store.add_trade_block_entry(conn, "7523", 1, "2026-09-22")
        trade_block_store.add_trade_block_entry(conn, "5927", 2, "2026-09-20")

        trade_block_store.remove_trade_block_entry(conn, "7523")

        assert trade_block_store.get_trade_block(conn) == (
            TradeBlockEntry(sleeper_id="5927", roster_id=2, added_date="2026-09-20"),
        )

    def test_removing_an_absent_entry_is_a_no_op(self, conn):
        trade_block_store.add_trade_block_entry(conn, "7523", 1, "2026-09-22")

        trade_block_store.remove_trade_block_entry(conn, "does-not-exist")

        assert trade_block_store.get_trade_block(conn) == (
            TradeBlockEntry(sleeper_id="7523", roster_id=1, added_date="2026-09-22"),
        )
