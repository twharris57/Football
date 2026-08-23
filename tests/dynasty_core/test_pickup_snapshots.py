"""Tests for dynasty_core.pickup_snapshots."""

from __future__ import annotations

import json

from dynasty_core import pickup_snapshots as ps
from dynasty_core.pickup_snapshots import _diff, _snapshot_path, reconcile_pickup_snapshot

EMPTY_SNAPSHOT = {"initialized": False, "players": {}}


def pool_player(team: str | None, depth_chart_order: int | None = None, status: str | None = None) -> dict:
    return {"team": team, "depth_chart_order": depth_chart_order, "status": status}


def tracked_player(team: str | None, depth_chart_order: int | None = None, status: str | None = None) -> dict:
    # Same shape as pool_player - separate name in the tests below that are
    # specifically about the *tracked universe* being broader than "the
    # current free-agent pool" (see RT-22 in PROJECT_PLAN_DYNASTY.md), so the two
    # concepts don't read as interchangeable just because they share a shape.
    return pool_player(team, depth_chart_order, status)


class TestDiff:
    def test_team_change_is_detected(self):
        previous = {"a": {"team": "KC", "depth_chart_order": None, "status": None}}
        pool = {"a": pool_player("BUF")}

        changes = _diff(previous, pool)

        assert changes == [{"player_id": "a", "kind": "team", "old": "KC", "new": "BUF"}]

    def test_first_appearance_in_an_already_initialized_snapshot_is_a_flaggable_team_change(self):
        # The central fix this design exists for: a player absent from
        # `previous` (but the snapshot as a whole is already established -
        # other players have real prior entries) is a real "just signed with
        # a team" event, not silently skipped. Skipping would permanently
        # miss this scenario, since there's no later point where the player
        # would suddenly acquire a "prior entry" to compare against. This
        # reading is only safe because the caller (reconcile_pickup_snapshot,
        # via fantasy_relevant_teamed_players) is expected to pass the *full*
        # teamed population, not just the free-agent subset - see
        # test_a_player_only_newly_available_but_already_tracked_is_not_a_false_signing
        # below for the case this would otherwise get wrong.
        previous = {"other_player": {"team": "SF", "depth_chart_order": 1, "status": "Active"}}
        pool = {"other_player": pool_player("SF", 1, "Active"), "new_player": pool_player("DAL")}

        changes = _diff(previous, pool)

        assert changes == [{"player_id": "new_player", "kind": "team", "old": None, "new": "DAL"}]

    def test_a_player_only_newly_available_but_already_tracked_is_not_a_false_signing(self):
        # RT-22 (2026-08-08 valuation review): a veteran who's been on the
        # same NFL team the whole time, but only just got dropped by a
        # fantasy manager, must NOT read as "just signed with {team}" - that
        # claim would be flatly wrong. The fix is at the wiring level
        # (reconcile_pickup_snapshot is now given the full
        # fantasy_relevant_teamed_players() population, not just the current
        # free-agent pool - see the module docstring), so this player already
        # has a real `previous` entry here even though they'd be "new" from a
        # free-agent-pool-only point of view. `_diff` itself doesn't know or
        # care about roster/pool status at all - only whether a prior entry
        # exists - which is exactly what makes tracking the right population
        # upstream the actual fix.
        previous = {"vet": tracked_player("KC", 4, "Active")}
        # "vet" was rostered by some fantasy team when last tracked and has
        # just been dropped - same real NFL team, nothing about their NFL
        # situation changed.
        universe = {"vet": tracked_player("KC", 4, "Active")}

        assert _diff(previous, universe) == []

    def test_depth_chart_order_improvement_is_detected(self):
        previous = {"a": {"team": "KC", "depth_chart_order": 3, "status": None}}
        pool = {"a": pool_player("KC", 1)}

        changes = _diff(previous, pool)

        assert changes == [{"player_id": "a", "kind": "depth_chart", "old": 3, "new": 1}]

    def test_depth_chart_order_regression_is_not_flagged(self):
        previous = {"a": {"team": "KC", "depth_chart_order": 1, "status": None}}
        pool = {"a": pool_player("KC", 3)}

        assert _diff(previous, pool) == []

    def test_status_transition_to_active_is_detected(self):
        previous = {"a": {"team": "KC", "depth_chart_order": None, "status": "Practice Squad"}}
        pool = {"a": pool_player("KC", status="Active")}

        changes = _diff(previous, pool)

        assert changes == [{"player_id": "a", "kind": "status", "old": "Practice Squad", "new": "Active"}]

    def test_status_staying_active_is_not_flagged(self):
        previous = {"a": {"team": "KC", "depth_chart_order": None, "status": "Active"}}
        pool = {"a": pool_player("KC", status="Active")}

        assert _diff(previous, pool) == []

    def test_unchanged_player_produces_no_diff(self):
        previous = {"a": {"team": "KC", "depth_chart_order": 2, "status": "Active"}}
        pool = {"a": pool_player("KC", 2, "Active")}

        assert _diff(previous, pool) == []

    def test_player_who_left_and_returned_diffs_against_retained_prior_values(self):
        # Retained from before they left the pool (see reconcile's merge
        # behavior) - a real change is still detectable, not treated as a
        # fresh first-sighting just because they were briefly off-pool.
        previous = {"a": {"team": "KC", "depth_chart_order": 4, "status": "Active"}}
        pool = {"a": pool_player("KC", 1, "Active")}

        changes = _diff(previous, pool)

        assert changes == [{"player_id": "a", "kind": "depth_chart", "old": 4, "new": 1}]


class TestReconcilePickupSnapshot:
    def test_true_first_ever_call_reports_no_changes_and_seeds_baseline(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ps, "CACHE_DIR", tmp_path)
        pool = {"a": pool_player("KC", 2, "Active"), "b": pool_player("DAL", 1, "Active")}

        updated, changes = reconcile_pickup_snapshot("league1", "2026", pool)

        assert changes == []
        assert updated["initialized"] is True
        assert updated["players"]["a"] == {"team": "KC", "depth_chart_order": 2, "status": "Active"}
        on_disk = json.loads(_snapshot_path("league1", "2026").read_text(encoding="utf-8"))
        assert on_disk == {**updated, "schema_version": ps.SCHEMA_VERSION}

    def test_second_call_with_a_real_change_surfaces_it_and_leaves_others_untouched(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ps, "CACHE_DIR", tmp_path)
        pool = {"a": pool_player("KC", 2, "Active"), "b": pool_player("DAL", 1, "Active")}
        reconcile_pickup_snapshot("league1", "2026", pool)

        moved_pool = {"a": pool_player("KC", 1, "Active"), "b": pool_player("DAL", 1, "Active")}
        updated, changes = reconcile_pickup_snapshot("league1", "2026", moved_pool)

        assert changes == [{"player_id": "a", "kind": "depth_chart", "old": 2, "new": 1}]
        assert updated["players"]["b"] == {"team": "DAL", "depth_chart_order": 1, "status": "Active"}

    def test_player_who_leaves_the_pool_is_retained_in_the_written_snapshot(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ps, "CACHE_DIR", tmp_path)
        pool = {"a": pool_player("KC", 2, "Active"), "b": pool_player("DAL", 1, "Active")}
        reconcile_pickup_snapshot("league1", "2026", pool)

        # "b" no longer in the pool (e.g. picked up by a fantasy team).
        updated, changes = reconcile_pickup_snapshot("league1", "2026", {"a": pool_player("KC", 2, "Active")})

        assert changes == []
        assert updated["players"]["b"] == {"team": "DAL", "depth_chart_order": 1, "status": "Active"}

    def test_a_real_pre_versioning_file_on_disk_loads_and_gets_stamped(self, tmp_path, monkeypatch):
        # Exactly the shape of every pickup_snapshots_*.json file that
        # exists today, written before schema_version was introduced.
        monkeypatch.setattr(ps, "CACHE_DIR", tmp_path)
        path = _snapshot_path("league1", "2026")
        path.write_text(
            json.dumps({"initialized": True, "players": {"a": {"team": "KC", "depth_chart_order": 2, "status": "Active"}}}),
            encoding="utf-8",
        )

        # Same pool as what's already on file - no real change to report.
        updated, changes = reconcile_pickup_snapshot("league1", "2026", {"a": pool_player("KC", 2, "Active")})

        assert changes == []
        assert updated["players"]["a"] == {"team": "KC", "depth_chart_order": 2, "status": "Active"}
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert on_disk["schema_version"] == ps.SCHEMA_VERSION
