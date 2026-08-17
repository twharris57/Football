"""Tests for dynasty_core.draft_snapshots."""

from __future__ import annotations

import json

from dynasty_core import draft_snapshots as ds
from dynasty_core.draft_snapshots import AMBIGUOUS, _reconcile, _snapshot_path, reconcile_snapshot
from dynasty_core.picks import DraftPickSlot

EMPTY_SNAPSHOT = {"confirmed_through_pick": 0, "confirmed_roster": None, "confirmed_drops": {}}


def own_picks(*overall_picks: int) -> list[DraftPickSlot]:
    return [DraftPickSlot(round=1, overall_pick=p, original_roster_id=1, owner_roster_id=1) for p in overall_picks]


class TestReconcile:
    def test_first_ever_call_sets_baseline_with_no_confirmed_drops(self):
        updated = _reconcile(EMPTY_SNAPSHOT, own_picks(1, 5), current_pick_no=6, current_roster_ids=["a", "b"], real_picks_by_overall={})

        assert updated == {
            "confirmed_through_pick": 5,
            "confirmed_roster": ["a", "b"],
            "confirmed_drops": {},
        }

    def test_one_newly_completed_pick_with_one_real_drop_is_confirmed(self):
        snapshot = {"confirmed_through_pick": 1, "confirmed_roster": ["a", "b", "old"], "confirmed_drops": {}}
        # Pick 5 added "new" and dropped "old" to make room.
        updated = _reconcile(
            snapshot,
            own_picks(1, 5),
            current_pick_no=6,
            current_roster_ids=["a", "b", "new"],
            real_picks_by_overall={5: "new"},
        )

        assert updated["confirmed_drops"] == {"5": "old"}
        assert updated["confirmed_through_pick"] == 5
        assert updated["confirmed_roster"] == ["a", "b", "new"]

    def test_one_newly_completed_pick_with_roster_room_is_confirmed_none(self):
        snapshot = {"confirmed_through_pick": 1, "confirmed_roster": ["a", "b"], "confirmed_drops": {}}
        # Pick 5 added "new" - nothing left the roster, there was room.
        updated = _reconcile(
            snapshot,
            own_picks(1, 5),
            current_pick_no=6,
            current_roster_ids=["a", "b", "new"],
            real_picks_by_overall={5: "new"},
        )

        assert updated["confirmed_drops"] == {"5": None}

    def test_two_newly_completed_picks_in_one_gap_are_all_ambiguous(self):
        snapshot = {"confirmed_through_pick": 1, "confirmed_roster": ["a", "b", "c"], "confirmed_drops": {}}
        updated = _reconcile(
            snapshot,
            own_picks(1, 5, 9),
            current_pick_no=10,
            current_roster_ids=["a", "new1", "new2"],
            real_picks_by_overall={5: "new1", 9: "new2"},
        )

        assert updated["confirmed_drops"] == {"5": AMBIGUOUS, "9": AMBIGUOUS}
        # The frontier still advances to the latest completed pick, even
        # though neither individual drop could be isolated.
        assert updated["confirmed_through_pick"] == 9

    def test_previously_confirmed_entry_is_never_recomputed(self):
        snapshot = {"confirmed_through_pick": 5, "confirmed_roster": ["a", "new1"], "confirmed_drops": {"5": "b"}}
        # A later gap spans two more picks - only the new ones should be
        # touched; pick 5's sticky "b" must survive unchanged.
        updated = _reconcile(
            snapshot,
            own_picks(5, 9, 13),
            current_pick_no=14,
            current_roster_ids=["new1", "new2", "new3"],
            real_picks_by_overall={9: "new2", 13: "new3"},
        )

        assert updated["confirmed_drops"]["5"] == "b"
        assert updated["confirmed_drops"]["9"] == AMBIGUOUS
        assert updated["confirmed_drops"]["13"] == AMBIGUOUS

    def test_no_newly_completed_picks_returns_snapshot_unchanged(self):
        snapshot = {"confirmed_through_pick": 5, "confirmed_roster": ["a"], "confirmed_drops": {"5": None}}
        updated = _reconcile(snapshot, own_picks(5), current_pick_no=6, current_roster_ids=["a"], real_picks_by_overall={})

        assert updated == snapshot


class TestReconcileSnapshot:
    def test_roundtrip_writes_and_reloads(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ds, "CACHE_DIR", tmp_path)

        first = reconcile_snapshot(
            "draft123", own_picks(1), current_pick_no=2, current_roster_ids=["a", "b"], real_picks_by_overall={}
        )
        assert first["confirmed_roster"] == ["a", "b"]

        on_disk = json.loads(_snapshot_path("draft123").read_text(encoding="utf-8"))
        assert on_disk == {**first, "schema_version": ds.SCHEMA_VERSION}

        # A second call with no newly-completed picks should reload the
        # same state from disk rather than resetting the baseline.
        second = reconcile_snapshot(
            "draft123", own_picks(1), current_pick_no=2, current_roster_ids=["a", "b"], real_picks_by_overall={}
        )
        assert second == first

    def test_a_real_pre_versioning_file_on_disk_loads_and_gets_stamped(self, tmp_path, monkeypatch):
        # Exactly the shape of every draft_snapshots_*.json file that
        # exists today, written before schema_version was introduced.
        monkeypatch.setattr(ds, "CACHE_DIR", tmp_path)
        path = _snapshot_path("draft123")
        path.write_text(
            json.dumps({"confirmed_through_pick": 5, "confirmed_roster": ["a", "b"], "confirmed_drops": {"5": None}}),
            encoding="utf-8",
        )

        updated = reconcile_snapshot(
            "draft123", own_picks(5), current_pick_no=6, current_roster_ids=["a", "b"], real_picks_by_overall={}
        )

        assert updated == {"confirmed_through_pick": 5, "confirmed_roster": ["a", "b"], "confirmed_drops": {"5": None}}
        # Nothing new was reconciled (no picks completed since pick 5), but
        # the file must still be rewritten with the current schema_version
        # rather than staying unstamped indefinitely.
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert on_disk["schema_version"] == ds.SCHEMA_VERSION
