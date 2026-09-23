"""Tests for dynasty_core.trade_block."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dynasty_core.trade_block import TradeBlockEntry, load_trade_block


def write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "trade_block.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestLoadTradeBlock:
    def test_missing_file_returns_empty_tuple(self, tmp_path):
        assert load_trade_block(tmp_path / "does_not_exist.json") == ()

    def test_well_formed_file_parses_into_entries(self, tmp_path):
        path = write(
            tmp_path,
            {
                "updated_at": "2026-09-22",
                "entries": [
                    {"sleeper_id": "7523", "roster_id": 1, "added_date": "2026-09-22"},
                    {"sleeper_id": "5927", "roster_id": 2, "added_date": "2026-09-20"},
                ],
            },
        )

        entries = load_trade_block(path)

        assert entries == (
            TradeBlockEntry(sleeper_id="7523", roster_id=1, added_date="2026-09-22"),
            TradeBlockEntry(sleeper_id="5927", roster_id=2, added_date="2026-09-20"),
        )

    def test_empty_entries_list_is_valid(self, tmp_path):
        path = write(tmp_path, {"updated_at": "2026-09-22", "entries": []})

        assert load_trade_block(path) == ()

    def test_unknown_top_level_key_is_rejected(self, tmp_path):
        path = write(tmp_path, {"updated_at": "2026-09-22", "entries": [], "notes": "extra"})

        with pytest.raises(ValueError, match="exactly the keys"):
            load_trade_block(path)

    def test_missing_entries_key_is_rejected(self, tmp_path):
        path = write(tmp_path, {"updated_at": "2026-09-22"})

        with pytest.raises(ValueError, match="exactly the keys"):
            load_trade_block(path)

    def test_malformed_updated_at_is_rejected(self, tmp_path):
        path = write(tmp_path, {"updated_at": "09/22/2026", "entries": []})

        with pytest.raises(ValueError, match="updated_at"):
            load_trade_block(path)

    def test_entry_with_unknown_key_is_rejected(self, tmp_path):
        path = write(
            tmp_path,
            {
                "updated_at": "2026-09-22",
                "entries": [{"sleeper_id": "7523", "roster_id": 1, "added_date": "2026-09-22", "name": "Trevor Lawrence"}],
            },
        )

        with pytest.raises(ValueError, match="entries\\[0\\]"):
            load_trade_block(path)

    def test_entry_with_missing_key_is_rejected(self, tmp_path):
        path = write(
            tmp_path,
            {"updated_at": "2026-09-22", "entries": [{"sleeper_id": "7523", "roster_id": 1}]},
        )

        with pytest.raises(ValueError, match="entries\\[0\\]"):
            load_trade_block(path)

    def test_non_string_sleeper_id_is_rejected(self, tmp_path):
        path = write(
            tmp_path,
            {"updated_at": "2026-09-22", "entries": [{"sleeper_id": 7523, "roster_id": 1, "added_date": "2026-09-22"}]},
        )

        with pytest.raises(ValueError, match="sleeper_id"):
            load_trade_block(path)

    def test_non_int_roster_id_is_rejected(self, tmp_path):
        path = write(
            tmp_path,
            {"updated_at": "2026-09-22", "entries": [{"sleeper_id": "7523", "roster_id": "1", "added_date": "2026-09-22"}]},
        )

        with pytest.raises(ValueError, match="roster_id"):
            load_trade_block(path)

    def test_bool_roster_id_is_rejected(self, tmp_path):
        # isinstance(True, int) is True in Python - explicitly guarded against
        # in the parser so a JSON `true`/`false` typo doesn't silently pass as
        # roster_id 1/0.
        path = write(
            tmp_path,
            {"updated_at": "2026-09-22", "entries": [{"sleeper_id": "7523", "roster_id": True, "added_date": "2026-09-22"}]},
        )

        with pytest.raises(ValueError, match="roster_id"):
            load_trade_block(path)

    def test_malformed_added_date_is_rejected(self, tmp_path):
        path = write(
            tmp_path,
            {"updated_at": "2026-09-22", "entries": [{"sleeper_id": "7523", "roster_id": 1, "added_date": "9/22/2026"}]},
        )

        with pytest.raises(ValueError, match="added_date"):
            load_trade_block(path)

    def test_non_zero_padded_added_date_is_rejected(self, tmp_path):
        path = write(
            tmp_path,
            {"updated_at": "2026-09-22", "entries": [{"sleeper_id": "7523", "roster_id": 1, "added_date": "2026-9-2"}]},
        )

        with pytest.raises(ValueError, match="added_date"):
            load_trade_block(path)

    def test_duplicate_sleeper_id_is_rejected(self, tmp_path):
        path = write(
            tmp_path,
            {
                "updated_at": "2026-09-22",
                "entries": [
                    {"sleeper_id": "7523", "roster_id": 1, "added_date": "2026-09-22"},
                    {"sleeper_id": "7523", "roster_id": 6, "added_date": "2026-09-22"},
                ],
            },
        )

        with pytest.raises(ValueError, match="duplicate sleeper_id"):
            load_trade_block(path)

    def test_entries_not_a_list_is_rejected(self, tmp_path):
        path = write(tmp_path, {"updated_at": "2026-09-22", "entries": {"sleeper_id": "7523"}})

        with pytest.raises(ValueError, match="entries must be a JSON array"):
            load_trade_block(path)

    def test_default_path_points_at_repo_checked_in_file(self):
        from dynasty_core.trade_block import TRADE_BLOCK_PATH

        # The real, checked-in trade_block.json - confirms load_trade_block()'s
        # default argument resolves to a real, parseable file, not just that
        # the parser works against synthetic tmp_path fixtures above.
        entries = load_trade_block(TRADE_BLOCK_PATH)
        assert all(isinstance(e, TradeBlockEntry) for e in entries)
