"""Tests for dynasty_core.draft_snapshots."""

from __future__ import annotations

import json
import os
import time

from dynasty_core import draft_snapshots as ds
from dynasty_core.draft_snapshots import (
    AMBIGUOUS,
    _delete_orphaned_snapshots,
    _mark_orphaned_snapshots,
    _reconcile,
    _snapshot_path,
    reconcile_snapshot,
)
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


def _age_file(path, days: float) -> None:
    old_time = time.time() - days * 86400
    os.utime(path, (old_time, old_time))


def _age_file_hours(path, hours: float) -> None:
    old_time = time.time() - hours * 3600
    os.utime(path, (old_time, old_time))


class TestMarkOrphanedSnapshots:
    def test_marks_an_old_file_from_a_different_draft(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ds, "CACHE_DIR", tmp_path)
        old_path = _snapshot_path("old_draft")
        old_path.write_text("{}", encoding="utf-8")
        _age_file(old_path, ds.ORPHAN_AGE_DAYS + 1)

        _mark_orphaned_snapshots("current_draft")

        assert not old_path.exists()
        assert (tmp_path / "draft_snapshots_old_draft.json.orphaned").exists()

    def test_leaves_a_recent_file_alone(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ds, "CACHE_DIR", tmp_path)
        recent_path = _snapshot_path("recent_draft")
        recent_path.write_text("{}", encoding="utf-8")

        _mark_orphaned_snapshots("current_draft")

        assert recent_path.exists()

    def test_never_touches_the_current_draft_even_if_old(self, tmp_path, monkeypatch):
        # Shouldn't happen in practice (an active draft's own file gets
        # rewritten on every real pick), but the current-draft file must
        # never be marked regardless of its age.
        monkeypatch.setattr(ds, "CACHE_DIR", tmp_path)
        current_path = _snapshot_path("current_draft")
        current_path.write_text("{}", encoding="utf-8")
        _age_file(current_path, ds.ORPHAN_AGE_DAYS + 1)

        _mark_orphaned_snapshots("current_draft")

        assert current_path.exists()

    def test_does_nothing_when_cache_dir_does_not_exist(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ds, "CACHE_DIR", tmp_path / "does_not_exist")

        _mark_orphaned_snapshots("current_draft")  # must not raise

    def test_already_marked_files_are_left_alone_on_a_later_sweep(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ds, "CACHE_DIR", tmp_path)
        old_path = _snapshot_path("old_draft")
        old_path.write_text("{}", encoding="utf-8")
        _age_file(old_path, ds.ORPHAN_AGE_DAYS + 1)
        _mark_orphaned_snapshots("current_draft")
        marked_path = tmp_path / "draft_snapshots_old_draft.json.orphaned"
        assert marked_path.exists()
        _age_file(marked_path, ds.ORPHAN_AGE_DAYS + 1)

        _mark_orphaned_snapshots("current_draft")  # second sweep

        assert marked_path.exists()  # still there, untouched - not re-marked or deleted

    def test_reconcile_snapshot_sweeps_orphans_as_a_side_effect(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ds, "CACHE_DIR", tmp_path)
        old_path = _snapshot_path("old_draft")
        old_path.write_text("{}", encoding="utf-8")
        _age_file(old_path, ds.ORPHAN_AGE_DAYS + 1)

        reconcile_snapshot(
            "current_draft", own_picks(1), current_pick_no=2, current_roster_ids=["a"], real_picks_by_overall={}
        )

        assert not old_path.exists()
        assert (tmp_path / "draft_snapshots_old_draft.json.orphaned").exists()

    def test_marking_stamps_the_orphaned_files_mtime_to_now(self, tmp_path, monkeypatch):
        # _delete_orphaned_snapshots()'s cooldown reads this mtime as "when
        # was this marked" - if marking didn't restamp it, an old
        # snapshot's already-90-day-stale mtime would let it slip past the
        # cooldown immediately, defeating the whole point of the cooldown.
        monkeypatch.setattr(ds, "CACHE_DIR", tmp_path)
        old_path = _snapshot_path("old_draft")
        old_path.write_text("{}", encoding="utf-8")
        _age_file(old_path, ds.ORPHAN_AGE_DAYS + 1)

        _mark_orphaned_snapshots("current_draft")

        marked_path = tmp_path / "draft_snapshots_old_draft.json.orphaned"
        assert time.time() - marked_path.stat().st_mtime < 5


class TestDeleteOrphanedSnapshots:
    def test_deletes_an_orphaned_file_past_the_cooldown(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ds, "CACHE_DIR", tmp_path)
        orphaned_path = tmp_path / "draft_snapshots_old_draft.json.orphaned"
        orphaned_path.write_text("{}", encoding="utf-8")
        _age_file_hours(orphaned_path, ds.ORPHAN_DELETE_COOLDOWN_HOURS + 1)

        _delete_orphaned_snapshots()

        assert not orphaned_path.exists()

    def test_leaves_a_freshly_marked_file_alone(self, tmp_path, monkeypatch):
        # A file that was *just* marked (mtime ~= now) must survive - the
        # cooldown is what gives a human a real window to notice and
        # rename a wrongly-marked file back, not just "one prior call."
        monkeypatch.setattr(ds, "CACHE_DIR", tmp_path)
        orphaned_path = tmp_path / "draft_snapshots_old_draft.json.orphaned"
        orphaned_path.write_text("{}", encoding="utf-8")

        _delete_orphaned_snapshots()

        assert orphaned_path.exists()

    def test_leaves_a_not_yet_orphaned_file_alone(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ds, "CACHE_DIR", tmp_path)
        active_path = _snapshot_path("current_draft")
        active_path.write_text("{}", encoding="utf-8")

        _delete_orphaned_snapshots()

        assert active_path.exists()

    def test_does_nothing_when_cache_dir_does_not_exist(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ds, "CACHE_DIR", tmp_path / "does_not_exist")

        _delete_orphaned_snapshots()  # must not raise

    def test_a_file_marked_orphaned_this_call_is_not_deleted_by_a_later_call_within_the_cooldown(
        self, tmp_path, monkeypatch
    ):
        # Two reconcile_snapshot() calls seconds apart (e.g. two quick
        # Refresh-button clicks - streamlit_app.py's cache-busting token
        # has no debounce) must not be enough to delete a just-marked file.
        # "Survived one prior call" alone isn't a real time buffer; the
        # cooldown is.
        monkeypatch.setattr(ds, "CACHE_DIR", tmp_path)
        old_path = _snapshot_path("old_draft")
        old_path.write_text("{}", encoding="utf-8")
        _age_file(old_path, ds.ORPHAN_AGE_DAYS + 1)
        orphaned_path = tmp_path / "draft_snapshots_old_draft.json.orphaned"

        reconcile_snapshot(
            "current_draft", own_picks(1), current_pick_no=2, current_roster_ids=["a"], real_picks_by_overall={}
        )
        assert orphaned_path.exists()  # marked, not deleted, on this call

        reconcile_snapshot(
            "current_draft", own_picks(1), current_pick_no=2, current_roster_ids=["a"], real_picks_by_overall={}
        )
        assert orphaned_path.exists()  # still not deleted - cooldown hasn't elapsed

    def test_a_marked_file_is_deleted_by_a_later_call_once_the_cooldown_has_elapsed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ds, "CACHE_DIR", tmp_path)
        orphaned_path = tmp_path / "draft_snapshots_old_draft.json.orphaned"
        orphaned_path.write_text("{}", encoding="utf-8")
        _age_file_hours(orphaned_path, ds.ORPHAN_DELETE_COOLDOWN_HOURS + 1)

        reconcile_snapshot(
            "current_draft", own_picks(1), current_pick_no=2, current_roster_ids=["a"], real_picks_by_overall={}
        )

        assert not orphaned_path.exists()
