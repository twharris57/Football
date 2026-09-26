"""Tests for dynasty_core.trade_block."""

from __future__ import annotations

from dynasty_core.trade_block import PrunedEntry, TradeBlockEntry, prune_stale_entries


def roster(roster_id: int, players: list[str]) -> dict:
    return {"roster_id": roster_id, "players": players}


class TestPruneStaleEntries:
    def test_entry_still_on_its_roster_is_kept(self):
        entry = TradeBlockEntry(sleeper_id="a", roster_id=1, added_date="2026-09-22")
        rosters_by_id = {1: roster(1, ["a", "b"])}

        kept, removed = prune_stale_entries((entry,), rosters_by_id)

        assert kept == (entry,)
        assert removed == ()

    def test_player_traded_to_a_different_roster_is_removed_as_traded(self):
        entry = TradeBlockEntry(sleeper_id="a", roster_id=1, added_date="2026-09-22")
        # "a" no longer on roster 1, now on roster 2 - a real trade, not a drop.
        rosters_by_id = {1: roster(1, ["b"]), 2: roster(2, ["a"])}

        kept, removed = prune_stale_entries((entry,), rosters_by_id)

        assert kept == ()
        assert removed == (PrunedEntry(entry=entry, reason="traded"),)

    def test_player_not_rostered_by_anyone_is_removed_as_dropped(self):
        entry = TradeBlockEntry(sleeper_id="a", roster_id=1, added_date="2026-09-22")
        # "a" gone from roster 1 and not on any other roster either - a real drop.
        rosters_by_id = {1: roster(1, ["b"]), 2: roster(2, ["c"])}

        kept, removed = prune_stale_entries((entry,), rosters_by_id)

        assert kept == ()
        assert removed == (PrunedEntry(entry=entry, reason="dropped"),)

    def test_roster_id_no_longer_present_is_treated_as_stale(self):
        entry = TradeBlockEntry(sleeper_id="a", roster_id=99, added_date="2026-09-22")
        rosters_by_id = {1: roster(1, ["b"])}

        kept, removed = prune_stale_entries((entry,), rosters_by_id)

        assert kept == ()
        assert removed == (PrunedEntry(entry=entry, reason="dropped"),)

    def test_mixed_kept_and_removed_entries_in_one_call(self):
        keep_entry = TradeBlockEntry(sleeper_id="a", roster_id=1, added_date="2026-09-22")
        traded_entry = TradeBlockEntry(sleeper_id="b", roster_id=1, added_date="2026-09-20")
        dropped_entry = TradeBlockEntry(sleeper_id="c", roster_id=2, added_date="2026-09-21")
        rosters_by_id = {
            1: roster(1, ["a"]),
            2: roster(2, ["b"]),
        }

        kept, removed = prune_stale_entries((keep_entry, traded_entry, dropped_entry), rosters_by_id)

        assert kept == (keep_entry,)
        assert removed == (
            PrunedEntry(entry=traded_entry, reason="traded"),
            PrunedEntry(entry=dropped_entry, reason="dropped"),
        )

    def test_no_entries_returns_empty_tuples(self):
        assert prune_stale_entries((), {}) == ((), ())
